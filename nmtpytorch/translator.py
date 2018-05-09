# -*- coding: utf-8 -*-
import sys
import math
import time
import logging
from pathlib import Path

from .utils.misc import load_pt_file
from .utils.filterchain import FilterChain

from . import models
from .config import Options
from .search import beam_search

logger = logging.getLogger('nmtpytorch')


class Translator(object):
    """A utility class to pack translation related features."""

    def __init__(self, **kwargs):
        # Store attributes directly. See bin/nmtpy for their list.
        self.__dict__.update(kwargs)

        for key, value in kwargs.items():
            logger.info('-- {} -> {}'.format(key, value))

        # How many models?
        self.n_models = len(self.models)

        # Store each model instance
        self.instances = []

        # Create model instances and move them to GPU
        for model_file in self.models:
            weights, _, opts = load_pt_file(model_file)
            opts = Options.from_dict(opts)
            # Create model instance
            instance = getattr(models, opts.train['model_type'])(opts=opts)

            if not instance.supports_beam_search:
                logger.error(
                    "Model does not support beam search. Try 'nmtpy test'")
                sys.exit(1)

            # Setup layers
            instance.setup(is_train=False)
            # Load weights
            instance.load_state_dict(weights, strict=True)
            # Move to GPU
            instance.cuda()
            # Switch to eval mode
            instance.train(False)
            self.instances.append(instance)

        # Do some sanity-check for ensembling compatibility
        self.sanity_check(self.instances)

        # Setup post-processing filters
        eval_filters = self.instances[0].opts.train['eval_filters']

        if self.disable_filters or not eval_filters:
            logger.info('Post-processing filters disabled.')
            self.filter = lambda s: s
        else:
            logger.info('Post-processing filters enabled.')
            self.filter = FilterChain(eval_filters)

        # Can be a comma separated list of hardcoded test splits
        if self.splits:
            logger.info('Will translate "{}"'.format(self.splits))
            self.splits = self.splits.split(',')
        elif self.source:
            # Split into key:value's and parse into dict
            input_dict = {}
            logger.info('Will translate input configuration:')
            for data_source in self.source.split(','):
                key, path = data_source.split(':', 1)
                input_dict[key] = Path(path)
                logger.info(' {}: {}'.format(key, input_dict[key]))
            self.instances[0].opts.data['new_set'] = input_dict
            self.splits = ['new']

    @staticmethod
    def sanity_check(instances):
        eval_filters = set([i.opts.train['eval_filters'] for i in instances])
        assert len(eval_filters) < 2, "eval_filters differ between instances."

        n_trg_vocab = set([i.n_trg_vocab for i in instances])
        assert len(n_trg_vocab) == 1, "target vocabularies differ."

    def translate(self, instances, split):
        """Returns the hypotheses generated by translating the given split
        using the given model instance.

        Arguments:
            instance(nn.Module): An initialized nmtpytorch model instance.
            split(str): A test split defined in the .conf file before
                training.

        Returns:
            list:
                A list of optionally post-processed string hypotheses.
        """

        # Load data
        self.instances[0].load_data(split)

        # NOTE: Data iteration needs to be unique for ensembling
        # otherwise it gets too complicated
        loader = self.instances[0].datasets[split].get_iterator(
            self.batch_size, drop_targets=True, inference=True)

        logger.info('Starting translation')
        start = time.time()
        hyps = beam_search(self.instances, loader,
                           beam_size=self.beam_size, max_len=self.max_len,
                           lp_alpha=self.lp_alpha)
        up_time = time.time() - start
        logger.info('Took {:.3f} seconds, {} sent/sec'.format(
            up_time, math.floor(len(hyps) / up_time)))

        return self.filter(hyps)

    def dump(self, hyps, split):
        """Writes the results into output.

        Arguments:
            hyps(list): A list of hypotheses.
        """
        suffix = ""
        if self.lp_alpha > 0.:
            suffix += ".lp_{:.1f}".format(self.lp_alpha)
        if self.n_models > 1:
            suffix += ".ens{}".format(self.n_models)
        suffix += ".beam{}".format(self.beam_size)

        if split == 'new':
            output = "{}{}".format(self.output, suffix)
        else:
            output = "{}.{}{}".format(self.output, split, suffix)

        with open(output, 'w') as f:
            for line in hyps:
                f.write(line + '\n')

    def __call__(self):
        """Dumps the hypotheses for each of the requested split/file."""
        for input_ in self.splits:
            # input_ can be a valid split name or 'new' when -S is given
            hyps = self.translate(self.instances, input_)
            self.dump(hyps, input_)
