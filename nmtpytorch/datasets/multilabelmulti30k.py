# -*- coding: utf-8 -*-
from torch.utils.data import DataLoader

from . import ImageFolderDataset, OneHotDataset
from . import MultiParallelDataset
from .collate import get_collate


class MultiLabelMulti30kDataset(object):
    """Returns a Dataset for multi-label Multi30k using raw JPG images.

    Arguments:
        data_dict(dict): [data] section's relevant split dictionary
        vocabs(dict): dictionary mapping lang keys to Vocabulary() objects
        topology(Topology): A topology object.
        warmup(bool, optional): If ``True``, raw images will be processed
            and cached once.
        resize (int, optional): An optional integer to be given to
            ``torchvision.transforms.Resize``. Default: ``256``.
        crop (int, optional): An optional integer to be given to
            ``torchvision.transforms.CenterCrop``. Default: ``224``.
        replicate(int, optional): Replicate the images ``replicate``
            times in order to process the same image that many times
            if ``replicate`` sentences are available during training time.
    """
    def __init__(self, data_dict, vocabs, topology,
                 warmup=False, resize=256, crop=224, replicate=1):

        self.topology = topology
        data = {}

        for src, ds in self.topology.srcs.copy().items():
            # Remove from topology if no data provided (possible in test time)
            if src not in data_dict:
                del self.topology.srcs[src]
                continue
            if ds._type == "ImageFolder":
                data[src] = ImageFolderDataset(
                    data_dict[src], resize=resize,
                    crop=crop, replicate=replicate, warmup=warmup)

        for trg, ds in self.topology.trgs.copy().items():
            # Remove from topology if no data provided (possible in test time)
            if trg not in data_dict:
                del self.topology.trgs[trg]
                continue
            path = data_dict[trg]
            data[trg] = OneHotDataset(path, vocabs[trg])

        # The keys (DataSource()) convey information about data sources
        self.dataset = MultiParallelDataset(
            src_datasets={v: data[k] for k, v in self.topology.srcs.items()},
            trg_datasets={v: data[k] for k, v in self.topology.trgs.items()},
        )

    def get_iterator(self, batch_size, drop_targets=False, inference=False):
        """Returns a DataLoader instance with or without target data.

        Arguments:
            batch_size (int): (Maximum) number of elements in a batch.
            drop_targets (bool, optional): If `True`, batches will not contain
                target-side data even that's available through configuration.
            inference (bool, optional): If `True`, batches will not be
                shuffled.
        """
        keys = self.dataset.sources if drop_targets else self.dataset.data_sources
        return DataLoader(
            self.dataset, shuffle=not inference, batch_size=batch_size,
            collate_fn=get_collate(keys))

    def __repr__(self):
        return self.dataset.__repr__()

    def __len__(self):
        return len(self.dataset)