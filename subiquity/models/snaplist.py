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

import json
import os

import attr

@attr.s(cmp=False)
class SnapInfo:
    name = attr.ib()
    summary = attr.ib()
    publisher = attr.ib()
    description = attr.ib()
    channels = attr.ib(default=attr.Factory(list))


@attr.s(cmp=False)
class ChannelSnapInfo:
    channel_name = attr.ib()
    revision = attr.ib()
    confinement = attr.ib()
    version = attr.ib()
    size = attr.ib()


class SnapListModel:
    """The overall model for subiquity."""

    def __init__(self, common):
        pass

    def get_snap_list(self):
        opd = os.path.dirname
        opj = os.path.join
        snap_data_dir = opj(opd(opd(opd(__file__))), 'examples', 'snaps')
        snap_find_output = opj(snap_data_dir, 'find-output.json')
        with open(snap_find_output) as fp:
            data = json.load(fp)
        r = []
        for s in data['result']:
            snap = SnapInfo(
                name=s['name'],
                summary=s['summary'],
                publisher=s['developer'],
                description=s['description'],
                )
            r.append(snap)
            snap_info_output = opj(snap_data_dir, 'info-{}.json'.format(snap.name))
            if os.path.exists(snap_info_output):
                with open(snap_info_output) as fp:
                    info = json.load(fp)['result'][0]
                channel_map = info['channels']
                for track in info['tracks']:
                    for risk in ["stable", "candidate", "beta", "edge"]:
                        channel_name = '{}/{}'.format(track, risk)
                        if channel_name in channel_map:
                            channel_data = channel_map[channel_name]
                            if track == "latest":
                                channel_name = risk
                            snap.channels.append(ChannelSnapInfo(
                                channel_name=channel_name,
                                revision=channel_data['revision'],
                                confinement=channel_data['confinement'],
                                version=channel_data['version'],
                                size=channel_data['size'],
                            ))
        return r

    def set_installed_list(self, to_install):
        self.to_install = to_install