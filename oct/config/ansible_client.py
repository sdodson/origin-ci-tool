# coding=utf-8
from __future__ import absolute_import, division, print_function

from functools import partial
from time import sleep

from __main__ import display
from ansible import constants
from ansible.cli.playbook import PlaybookCLI
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.inventory import Inventory
from ansible.parsing.dataloader import DataLoader
from ansible.plugins import callback_loader
from ansible.vars import VariableManager
from click import ClickException
from os import environ
from os.path import abspath, dirname, join

DEFAULT_VERBOSITY = 1


class AnsibleCoreClient(object):
    """
    This is both a container that holds configuration
    options for the Ansible core and a client for the
    Ansible Core, allowing us to run playbooks.
    """

    def __init__(self,
                 inventory_file=None,
                 verbosity=DEFAULT_VERBOSITY,
                 dry_run=False,
                 log_directory=None):
        if inventory_file is None:
            # default to the dynamic Vagrant inventory
            from ..vagrant import __file__ as inventory_directory
            inventory_file = join(abspath(dirname(inventory_directory)), 'inventory.py')

        # location of the inventory file to use
        self.host_list = inventory_file
        # verbosity level for Ansible output
        self.verbosity = verbosity
        # whether or not to make changes on the remote host
        self.check = dry_run
        # where to store logs for Ansible playbooks
        self.log_directory = log_directory

    def generate_playbook_options(self, playbook):
        """
        Use the Ansible CLI code to generate a set of options
        for the Playbook API. We do not know or care about the
        fields that may or may not be needed from the options,
        so we let the Ansible code parse them out and set other
        defaults as necessary.
        :return: namedtuple-esque playbook options object
        """
        playbook_args = [
            'ansible-playbook',
            '-{}'.format('v' * self.verbosity),
            playbook
        ]

        if self.check:
            playbook_args.append('--check')

        playbook_cli = PlaybookCLI(args=playbook_args)
        playbook_cli.parse()

        return playbook_cli.options

    def run_playbook(self, playbook_file, playbook_variables=None):
        """
        Run a playbook from file with the variables provided.

        :param playbook_file: the location of the playbook
        :param playbook_variables: extra variables for the playbook
        """
        variable_manager = VariableManager()
        data_loader = DataLoader()
        inventory = Inventory(
            loader=data_loader,
            variable_manager=variable_manager,
            host_list=self.host_list
        )
        variable_manager.set_inventory(inventory)
        variable_manager.extra_vars = playbook_variables

        # until Ansible's display logic is less hack-ey we need
        # to mutate their global in __main__
        options = self.generate_playbook_options(playbook_file)
        display.verbosity = options.verbosity

        # we want to log everything so we can parse output
        # nicely later from files and don't miss output due
        # to the pretty printer, if it's on
        from ..oct import __file__ as root_dir
        callback_loader.add_directory(join(dirname(root_dir), 'ansible', 'oct', 'callback_plugins'))
        constants.DEFAULT_CALLBACK_WHITELIST = 'log_results'
        environ['ANSIBLE_LOG_ROOT_PATH'] = self.log_directory

        if options.verbosity == 1:
            # if the user has not asked for verbose output
            # we will use our pretty printer for progress
            # on the TTY
            constants.DEFAULT_STDOUT_CALLBACK = 'pretty_progress'

            # we really don't want output in std{err,out}
            # that we didn't put there, but some code in
            # Ansible calls directly to the Display, not
            # through a callback, so we need to ensure
            # that those raw calls don't go to stdout
            display.display = partial(display.display, log_only=True)

        result = PlaybookExecutor(
            playbooks=[playbook_file],
            inventory=inventory,
            variable_manager=variable_manager,
            loader=data_loader,
            options=options,
            passwords=None
        ).run()

        if result != TaskQueueManager.RUN_OK:
            # TODO: this seems bad, but can we discover the thread here to join() it?
            sleep(0.2)
            raise ClickException('Playbook execution failed with code ' + str(result))