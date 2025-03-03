# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from unittest.mock import ANY, call, Mock

import pytest
from torch.utils.data import DataLoader

import pytorch_lightning as pl
from pytorch_lightning import Trainer
from pytorch_lightning.callbacks import BasePredictionWriter
from pytorch_lightning.demos.boring_classes import BoringModel, RandomDataset
from pytorch_lightning.trainer.supporters import CombinedLoader
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests.helpers.runif import RunIf


class DummyPredictionWriter(BasePredictionWriter):
    def write_on_batch_end(self, *args, **kwargs):
        pass

    def write_on_epoch_end(self, *args, **kwargs):
        pass


def test_prediction_writer_invalid_write_interval():
    """Test that configuring an unknown interval name raises an error."""
    with pytest.raises(MisconfigurationException, match=r"`write_interval` should be one of \['batch"):
        DummyPredictionWriter("something")


def test_prediction_writer_hook_call_intervals(tmpdir):
    """Test that the `write_on_batch_end` and `write_on_epoch_end` hooks get invoked based on the defined
    interval."""
    DummyPredictionWriter.write_on_batch_end = Mock()
    DummyPredictionWriter.write_on_epoch_end = Mock()

    dataloader = DataLoader(RandomDataset(32, 64))

    model = BoringModel()
    cb = DummyPredictionWriter("batch_and_epoch")
    trainer = Trainer(limit_predict_batches=4, callbacks=cb)
    results = trainer.predict(model, dataloaders=dataloader)
    assert len(results) == 4
    assert cb.write_on_batch_end.call_count == 4
    assert cb.write_on_epoch_end.call_count == 1

    DummyPredictionWriter.write_on_batch_end.reset_mock()
    DummyPredictionWriter.write_on_epoch_end.reset_mock()

    cb = DummyPredictionWriter("batch_and_epoch")
    trainer = Trainer(limit_predict_batches=4, callbacks=cb)
    trainer.predict(model, dataloaders=dataloader, return_predictions=False)
    assert cb.write_on_batch_end.call_count == 4
    assert cb.write_on_epoch_end.call_count == 1

    DummyPredictionWriter.write_on_batch_end.reset_mock()
    DummyPredictionWriter.write_on_epoch_end.reset_mock()

    cb = DummyPredictionWriter("batch")
    trainer = Trainer(limit_predict_batches=4, callbacks=cb)
    trainer.predict(model, dataloaders=dataloader, return_predictions=False)
    assert cb.write_on_batch_end.call_count == 4
    assert cb.write_on_epoch_end.call_count == 0

    DummyPredictionWriter.write_on_batch_end.reset_mock()
    DummyPredictionWriter.write_on_epoch_end.reset_mock()

    cb = DummyPredictionWriter("epoch")
    trainer = Trainer(limit_predict_batches=4, callbacks=cb)
    trainer.predict(model, dataloaders=dataloader, return_predictions=False)
    assert cb.write_on_batch_end.call_count == 0
    assert cb.write_on_epoch_end.call_count == 1


@pytest.mark.parametrize("num_workers", [0, pytest.param(2, marks=RunIf(slow=True))])
def test_prediction_writer_batch_indices(tmpdir, num_workers):
    DummyPredictionWriter.write_on_batch_end = Mock()
    DummyPredictionWriter.write_on_epoch_end = Mock()

    dataloader = DataLoader(RandomDataset(32, 64), batch_size=4, num_workers=num_workers)
    model = BoringModel()
    writer = DummyPredictionWriter("batch_and_epoch")
    trainer = Trainer(limit_predict_batches=4, callbacks=writer)
    trainer.predict(model, dataloaders=dataloader)

    writer.write_on_batch_end.assert_has_calls(
        [
            call(trainer, model, ANY, [0, 1, 2, 3], ANY, 0, 0),
            call(trainer, model, ANY, [4, 5, 6, 7], ANY, 1, 0),
            call(trainer, model, ANY, [8, 9, 10, 11], ANY, 2, 0),
            call(trainer, model, ANY, [12, 13, 14, 15], ANY, 3, 0),
        ]
    )

    writer.write_on_epoch_end.assert_has_calls(
        [
            call(trainer, model, ANY, [[[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]]]),
        ]
    )


def test_prediction_writer_partial_support_for_combined_loader(tmpdir):
    """Test partial support for CombinedLoader: prediction works but sample indices don't get tracked."""
    pl.loops.epoch.prediction_epoch_loop.warning_cache.clear()

    class PredictionModel(BoringModel):
        def predict_dataloader(self):
            return CombinedLoader(
                {
                    "a": DataLoader(RandomDataset(32, 8), batch_size=2),
                    "b": DataLoader(RandomDataset(32, 8), batch_size=4),
                }
            )

        def predict_step(self, batch, *args, **kwargs):
            return self(batch["a"])

    DummyPredictionWriter.write_on_batch_end = Mock()
    DummyPredictionWriter.write_on_epoch_end = Mock()

    model = PredictionModel()
    writer = DummyPredictionWriter("batch_and_epoch")
    trainer = Trainer(callbacks=writer)
    with pytest.warns(UserWarning, match="Lightning couldn't infer the indices fetched for your dataloader."):
        trainer.predict(model)

    writer.write_on_batch_end.assert_has_calls(
        [call(trainer, model, ANY, [], ANY, 0, 0), call(trainer, model, ANY, [], ANY, 1, 0)]
    )

    writer.write_on_epoch_end.assert_has_calls([call(trainer, model, ANY, [[]])])
