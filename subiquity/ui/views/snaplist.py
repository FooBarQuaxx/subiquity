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

import logging

from urwid import (
    BOX,
    CheckBox,
    Text,
    Widget,
    WidgetWrap,
    )

from subiquitycore.ui.buttons import ok_btn, cancel_btn, other_btn
from subiquitycore.ui.container import Columns, ListBox, Pile
from subiquitycore.ui.utils import button_pile, Color, Padding, screen
from subiquitycore.view import BaseView

from subiquity.models.filesystem import humanize_size

log = logging.getLogger("subiquity.views.snaplist")

class SnapInfoView(Widget):
    _selectable = True
    _sizing = frozenset([BOX])
    description_index = 5
    channels_index = 7
    def __init__(self, parent, snap):
        self.parent = parent
        self.channels = []
        self.needs_focus = True
        max_channel_name = max(len(csi.channel_name) for csi in snap.channels)
        max_version = max(len(csi.version) for csi in snap.channels)
        for csi in snap.channels:
            notes = '-'
            if csi.confinement != "strict":
                notes = csi.confinement
            self.channels.append(Columns([
                (max_channel_name+5, CheckBox("{}:".format(csi.channel_name))),
                (max_version, Text(csi.version)),
                ('pack', Text("({})".format(csi.revision))),
                ('pack', Text(humanize_size(csi.size))),
                ('pack', Text(notes)),
                ], dividechars=1))
        self.description = Text(snap.description.replace('\r', '').strip())
        self.lb_description = Padding.center_79(ListBox([self.description]))
        self.lb_channels = Padding.center_79(ListBox(self.channels))
        self.pile = Pile([
            ('pack', Text("")),
            ('pack', Padding.center_79(Text("{} - {}".format(snap.name, snap.publisher)))),
            ('pack', Text("")),
            ('pack', Padding.center_79(Text(snap.summary))),
            ('pack', Text("")),
            self.lb_description,
            ('pack', Text("")),
            ('weight', 1, self.lb_channels),
            ('pack', Text("")),
            ('pack', button_pile([other_btn(label=_("Close"), on_press=self.cancel)])),
            ('pack', Text("")),
            ])
    def cancel(self, sender=None):
        self.parent._w = self.parent.main_screen
    def keypress(self, size, key):
        return self.pile.keypress(size, key)
    def render(self, size, focus):
        maxcol, maxrow = size
        rows_available = maxrow
        pack_option = self.pile.options('pack')
        for w, o in self.pile.contents:
            if o == pack_option:
                rows_available -= w.rows((maxcol,), focus)
        rows_wanted_description = Padding.center_79(self.description).rows((maxcol,), False)
        rows_wanted_channels = len(self.channels)
        if rows_wanted_channels + rows_wanted_description < rows_available:
            self.pile.contents[self.description_index] = (self.lb_description, self.pile.options('given', rows_wanted_description))
            if self.needs_focus:
                self.pile.focus_position = self.channels_index
                self.needs_focus = False
        else:
            channel_rows = min(rows_wanted_channels, int(rows_available/3))
            description_rows = rows_available - channel_rows
            self.pile.contents[self.description_index] = (self.lb_description, self.pile.options('given', description_rows))
            if self.needs_focus:
                if description_rows >= rows_wanted_description:
                    self.pile.focus_position = self.channels_index
                else:
                    self.pile.focus_position = self.description_index
                self.needs_focus = False
        return self.pile.render(size, focus)

class SnapListRow(WidgetWrap):
    def __init__(self, parent, snap, max_name_len, max_publisher_len):
        self.parent = parent
        self.snap = snap
        super().__init__(Color.menu_button(Columns([
                (max_name_len+4, CheckBox(snap.name)),
                Text(snap.summary, wrap='clip'),
                ], dividechars=1)))
    def keypress(self, size, key):
        if key.startswith("enter"):
            self.parent._w = self.parent.snap_info_screen(self.snap)
            return
        return super().keypress(size, key)

class SnapListView(BaseView):

    def __init__(self, model, controller):
        self.model = model
        self.controller = controller
        self.to_install = []
        body = []
        snaps = self.model.get_snap_list()
        self.name_len = max([len(snap.name) for snap in snaps])
        self.publisher_len = max([len(snap.publisher) for snap in snaps])
        for snap in snaps:
            body.append(SnapListRow(self, snap, self.name_len, self.publisher_len))
        ok = ok_btn(label=_("OK"), on_press=self.done)
        cancel = cancel_btn(label=_("Cancel"), on_press=self.done)
        self.main_screen = screen(
            body, button_pile([ok, cancel]),
            focus_buttons=False,
            excerpt=_("These are popular snaps in server environments. Select or deselect with SPACE, press ENTER to see more details of the package, publisher and versions available."))
        self.snap_screens = {}
        super().__init__(self.main_screen)

    def snap_info_screen(self, snap):
        if snap.name in self.snap_screens:
            return self.snap_screens[snap.name]


        screen = self.snap_screens[snap.name] = SnapInfoView(self, snap)
        return screen

    def done(self, sender=None):
        self.controller.done(self.to_install)

    def cancel(self, sender=None):
        if self._w is self.main_screen:
            self.controller.cancel()
        else:
            self._w = self.main_screen
