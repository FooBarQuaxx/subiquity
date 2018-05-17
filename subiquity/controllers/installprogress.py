# Copyright 2015 Canonical, Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import datetime
import json
import logging
import os
import subprocess
import time

import urwid
import yaml

from systemd import journal

from subiquitycore import utils
from subiquitycore.controller import BaseController

from subiquity.ui.views.installprogress import ProgressView


log = logging.getLogger("subiquitycore.controller.installprogress")

TARGET = '/target'

class InstallState:
    NOT_STARTED = 0
    RUNNING = 1
    DONE = 2
    ERROR = -1



raw_lxc_config = '''\
lxc.hook.version = 1
lxc.hook.pre-start = 'sh -c "mkdir -p $LXC_ROOTFS_PATH && mount --bind /target $LXC_ROOTFS_PATH"'
lxc.hook.post-stop = 'sh -c "umount $LXC_ROOTFS_PATH"'
'''

class ContainerManager(object):
    def __init__(self):
        self.container_name = 'target'
        self.nic_name = 'lxd-nic'

    def container_config(self):
        return json.dumps({
            'source': {
                "type": "none",
                },
            'config': {
                'security.privileged': '1',
                'raw.lxc': raw_lxc_config,
                },
            'name': self.container_name,
            })

    def preseed(self):
        return yaml.dump({
            'networks': [{
                'name': 'lxdbr0',
                'type': 'bridge',
                'config': {
                    'ipv4.address': 'auto',
                    'ipv6.address': 'auto',
                    },
                }],
            'storage_pools': [{
                'name': 'default',
                'driver': 'dir',
                }],
            'profiles': [{
                'name': 'default',
                'devices': {
                    'root': {
                        'type': 'disk',
                        'pool': 'default',
                        'path': '/',
                        },
                    self.nic_name: {
                        'type': 'nic',
                        'nictype': 'bridged',
                        'parent': 'lxdbr0',
                        'name': self.nic_name,
                        },
                    },
                }],
            })

    def netplan_for_container(self):
        return yaml.dump({
            'network': {
                'version': 2,
                'ethernets': {
                    self.nic_name: {
                        'dhcp4': True,
                        },
                    },
                },
            })

    def initialize_lxd(self):
        subprocess.run(
            ["lxd", "init", "--preseed"],
            input=self.preseed().encode('ascii'),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True)

    def create_container(self):
        subprocess.run(
            ["lxc", "query", "--wait", "--request", "POST", "--data", self.container_config(), "/1.0/containers"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True)

    def start_container(self):
        subprocess.run(
            ["lxc", "start", self.container_name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True)

    def run(self, cmd):
        p = subprocess.run(
            ["lxc", "exec", self.container_name, "--"] + cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True)
        return p.stdout

    def wait_for_cloudinit(self):
        return self.run(["cloud-init", "status", "--wait"]),

    def enable_networking(self):
        self.run(["mkdir",  "-p", "/run/netplan"])
        subprocess.run(
            ["lxc", "file", "push", "-", self.container_name + "/run/netplan/tmp.yaml"],
            input=self.netplan_for_container().encode('ascii'),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=True)
        self.run(["netplan", "apply"])
        while 'default' not in self.run(["ip", "route"]):
            time.sleep(0.1)


class InstallProgressController(BaseController):
    signals = [
        ('installprogress:filesystem-config-done', 'filesystem_config_done'),
        ('installprogress:identity-config-done',   'identity_config_done'),
    ]

    def __init__(self, common):
        super().__init__(common)
        self.answers = self.all_answers.get('InstallProgress', {})
        self.answers.setdefault('reboot', False)
        self.progress_view = None
        self.progress_view_showing = False
        self.install_state = InstallState.NOT_STARTED
        self.journal_listener_handle = None
        self._identity_config_done = False
        self._event_indent = ""
        self._event_syslog_identifier = 'curtin_event.%s' % (os.getpid(),)
        self._log_syslog_identifier = 'curtin_log.%s' % (os.getpid(),)
        self.cm = ContainerManager()
        if not self.opts.dry_run:
            self.run_in_bg(self._bg_setup_lxd, lambda fut:None)

    def _bg_setup_lxd(self):
        self.cm.initialize_lxd()
        self.cm.create_container()

    def filesystem_config_done(self):
        self.curtin_start_install()

    def identity_config_done(self):
        if self.install_state == InstallState.DONE:
            self.postinstall_configuration()
        else:
            self._identity_config_done = True

    def curtin_error(self):
        log.debug('curtin_error')
        self.install_state = InstallState.ERROR
        self.progress_view.spinner.stop()
        self.progress_view.set_status(('info_error', _("An error has occurred")))
        self.progress_view.show_complete(True)
        self.default()

    def _bg_run_command_logged(self, cmd, env):
        log.debug("running %s", cmd)
        cmd = ['systemd-cat', '--level-prefix=false', '--identifier=' + self._log_syslog_identifier] + cmd
        cp = subprocess.run(cmd, env=env)
        log.debug("completed %s", cmd)
        return cp.returncode

    def _journal_event(self, event):
        if event['SYSLOG_IDENTIFIER'] == self._event_syslog_identifier:
            self.curtin_event(event)
        elif event['SYSLOG_IDENTIFIER'] == self._log_syslog_identifier:
            self.curtin_log(event)

    def _install_event_start(self, message):
        self.footer_description.set_text(message)
        self.progress_view.add_event(self._event_indent + message)
        self._event_indent += "  "
        self.footer_spinner.start()

    def _install_event_finish(self):
        self._event_indent = self._event_indent[:-2]
        self.footer_spinner.stop()

    def curtin_event(self, event):
        e = {}
        for k, v in event.items():
            if k.startswith("CURTIN_"):
                e[k] = v
        log.debug("curtin_event received %r", e)
        event_type = event.get("CURTIN_EVENT_TYPE")
        if event_type not in ['start', 'finish']:
            return
        if event_type == 'start':
            self._install_event_start(event.get("CURTIN_MESSAGE", "??"))
        if event_type == 'finish':
            self._install_event_finish()

    def curtin_log(self, event):
        self.progress_view.add_log_line(event['MESSAGE'])

    def start_journald_listener(self, identifiers, callback):
        reader = journal.Reader()
        args = []
        for identifier in identifiers:
            args.append("SYSLOG_IDENTIFIER={}".format(identifier))
        reader.add_match(*args)
        #reader.seek_tail()
        def watch():
            if reader.process() != journal.APPEND:
                return
            for event in reader:
                callback(event)
        return self.loop.watch_file(reader.fileno(), watch)

    def _write_config(self, path, config):
        with open(path, 'w') as conf:
            datestr = '# Autogenerated by SUbiquity: {} UTC\n'.format(
                str(datetime.datetime.utcnow()))
            conf.write(datestr)
            conf.write(yaml.dump(config))

    def _get_curtin_command(self):
        config_file_name = 'subiquity-curtin-install.conf'

        if self.opts.dry_run:
            log.debug("Installprogress: this is a dry-run")
            config_location = os.path.join('.subiquity/', config_file_name)
            curtin_cmd = [
                "python3", "scripts/replay-curtin-log.py", "examples/curtin-events.json", self._event_syslog_identifier,
                ]
        else:
            log.debug("Installprogress: this is the *REAL* thing")
            config_location = os.path.join('/var/log/installer', config_file_name)
            curtin_cmd = ['curtin', '--showtrace', '-c', config_location, 'install']

        self._write_config(
            config_location,
            self.base_model.render(target=TARGET, syslog_identifier=self._event_syslog_identifier))

        return curtin_cmd

    def curtin_start_install(self):
        log.debug('Curtin Install: starting curtin')
        self.install_state = InstallState.RUNNING
        self.footer_description = urwid.Text(_("starting..."))
        self.progress_view = ProgressView(self)
        self.footer_spinner = self.progress_view.spinner

        self.ui.set_footer(urwid.Columns([('pack', urwid.Text(_("Install in progress:"))), (self.footer_description), ('pack', self.footer_spinner)], dividechars=1))

        self.journal_listener_handle = self.start_journald_listener([self._event_syslog_identifier, self._log_syslog_identifier], self._journal_event)

        curtin_cmd = self._get_curtin_command()

        log.debug('Curtin install cmd: {}'.format(curtin_cmd))
        env = os.environ.copy()
        if 'SNAP' in env:
            del env['SNAP']
        self.run_in_bg(
            lambda: self._bg_run_command_logged(curtin_cmd, env),
            self.curtin_install_completed)

    def curtin_install_completed(self, fut):
        returncode = fut.result()
        log.debug('curtin_install: returncode: {}'.format(returncode))
        if returncode != 0:
            self.curtin_error()
            return
        self.install_state = InstallState.DONE
        log.debug('After curtin install OK')
        self.loop.set_alarm_in(0.01, lambda loop, userdata: self.install_complete())

    def cancel(self):
        pass

    def install_complete(self):
        self.ui.progress_current += 1
        if not self.progress_view_showing:
            self.ui.set_footer(_("Install complete"))
        else:
            # Re-set footer so progress bar updates.
            self.ui.set_footer(_("Thank you for using Ubuntu!"))
        if self._identity_config_done:
            self.postinstall_configuration()

    def postinstall_configuration(self):
        # If we need to do anything that takes time here (like running
        # dpkg-reconfigure maas-rack-controller, for example...) we
        # should switch to doing that work in a background thread.
        self.configure_cloud_init()
        self.copy_logs_to_target()

        self._install_event_start("post install configuration")
        self._install_event_start("starting container")

        self.run_in_bg(self.cm.start_container, self._container_started)

    def _container_started(self, fut):
        self._install_event_finish()
        self._install_event_start("waiting for boot to complete")
        self.run_in_bg(self.cm.wait_for_cloudinit, self.postinstall_complete)

    def postinstall_complete(self, fut):
        self._install_event_finish()
        self._install_event_finish()
        self.ui.set_header(_("Installation complete!"))
        self.progress_view.set_status(_("Finished install!"))
        self.progress_view.show_complete()

        if self.answers['reboot']:
            self.loop.set_alarm_in(0.01, lambda loop, userdata: self.reboot())

    def configure_cloud_init(self):
        if self.opts.dry_run:
            target = '.subiquity'
        else:
            target = TARGET
        self.base_model.configure_cloud_init(target)

    def copy_logs_to_target(self):
        if self.opts.dry_run:
            return
        utils.run_command(['cp', '-aT', '/var/log/installer', '/target/var/log/installer'])
        try:
            with open('/target/var/log/installer/installer-journal.txt', 'w') as output:
                subprocess.run(
                    ['journalctl'],
                    stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except Exception:
            log.exception("saving journal failed")

    def reboot(self):
        if self.opts.dry_run:
            log.debug('dry-run enabled, skipping reboot, quiting instead')
            self.signal.emit_signal('quit')
        else:
            # Should probably run curtin -c $CONFIG unmount -t TARGET first.
            utils.run_command(["/sbin/reboot"])

    def quit(self):
        if not self.opts.dry_run:
            utils.disable_subiquity()
        self.signal.emit_signal('quit')

    def default(self):
        self.progress_view_showing = True
        self.ui.set_body(self.progress_view)
        if self.install_state == InstallState.RUNNING:
            self.ui.set_header(_("Installing system"))
            self.ui.set_footer(_("Thank you for using Ubuntu!"))
        elif self.install_state == InstallState.DONE:
            self.ui.set_header(_("Install complete!"))
            self.ui.set_footer(_("Thank you for using Ubuntu!"))
        elif self.install_state == InstallState.ERROR:
            self.ui.set_header(_('An error occurred during installation'))
            self.ui.set_footer(_('Please report this error in Launchpad'))

