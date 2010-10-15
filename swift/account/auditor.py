# Copyright (c) 2010 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import time
from random import random

from swift.account import server as account_server
from swift.common.db import AccountBroker
from swift.common.utils import get_logger
from swift.common.daemon import Daemon


class AccountAuditor(Daemon):
    """Audit accounts."""

    def __init__(self, conf):
        self.conf = conf
        self.logger = get_logger(conf, 'account-auditor')
        self.devices = conf.get('devices', '/srv/node')
        self.mount_check = conf.get('mount_check', 'true').lower() in \
                              ('true', 't', '1', 'on', 'yes', 'y')
        self.interval = int(conf.get('interval', 1800))
        self.account_passes = 0
        self.account_failures = 0

    def audit_location_generator(self, datadir):
        for device in os.listdir(self.devices):
            if self.mount_check and not\
                    os.path.ismount(os.path.join(self.devices, device)):
                self.logger.debug(
                    'Skipping %s as it is not mounted' % device)
                continue
            datadir = os.path.join(self.devices, device, datadir)
            if not os.path.exists(datadir):
                continue
            partitions = os.listdir(datadir)
            for partition in partitions:
                part_path = os.path.join(datadir, partition)
                if not os.path.isdir(part_path):
                    continue
                suffixes = os.listdir(part_path)
                for suffix in suffixes:
                    suff_path = os.path.join(part_path, suffix)
                    if not os.path.isdir(suff_path):
                        continue
                    hashes = os.listdir(suff_path)
                    for hsh in hashes:
                        hash_path = os.path.join(suff_path, hsh)
                        if not os.path.isdir(hash_path):
                            continue
                        for fname in sorted(os.listdir(hash_path),
                                            reverse=True):
                            path = os.path.join(hash_path, fname)
                            yield path, device, partition

    def run_forever(self):  # pragma: no cover
        """Run the account audit until stopped."""
        reported = time.time()
        time.sleep(random() * self.interval)
        while True:
            begin = time.time()
            all_locs = self.audit_location_generator(account_server.DATADIR)
            for path, device, partition in all_locs:
                self.account_audit(path)
                if time.time() - reported >= 3600:  # once an hour
                    self.logger.info(
                        'Since %s: Account audits: %s passed audit, '
                        '%s failed audit' % (time.ctime(reported),
                                            self.account_passes,
                                            self.account_failures))
                    reported = time.time()
                    self.account_passes = 0
                    self.account_failures = 0
            elapsed = time.time() - begin
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)

    def run_once(self):
        """Run the account audit once."""
        self.logger.info('Begin account audit "once" mode')
        begin = time.time()
        try:
            location = ''
            gen = self.audit_location_generator(account_server.DATADIR)
            while not location.endswith('.db'):
                location, device, partition = gen.next()
        except StopIteration:
            self.logger.info('Nothing to audit')
        else:
            self.account_audit(location)
        elapsed = time.time() - begin
        self.logger.info(
            'Account audit "once" mode completed: %.02fs' % elapsed)

    def account_audit(self, path):
        """
        Audits the given account path

        :param path: the path to an account db
        """
        try:
            if not path.endswith('.db'):
                return
            broker = AccountBroker(path)
            if not broker.is_deleted():
                info = broker.get_info()
                self.account_passes += 1
                self.logger.debug('Audit passed for %s' % broker.db_file)
        except Exception:
            self.account_failures += 1
            self.logger.error('ERROR Could not get account info %s' %
                (broker.db_file))
