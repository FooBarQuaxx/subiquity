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
    LineBox,
    Text,
    SimpleFocusListWalker,
    )

from subiquitycore.view import BaseView
from subiquitycore.ui.buttons import cancel_btn, ok_btn, other_btn
from subiquitycore.ui.container import Columns, ListBox, Pile
from subiquitycore.ui.utils import button_pile, Padding

from subiquity.ui.spinner import Spinner

log = logging.getLogger("subiquity.views.installprogress")

class MyLineBox(LineBox):
    def format_title(self, title):
        if title:
            return [" ", title, " "]
        else:
            return ""


class ProgressView(BaseView):
    def __init__(self, controller):
        self.controller = controller
        self.spinner = Spinner(controller.loop)

        self.event_listwalker = SimpleFocusListWalker([])
        self.event_listbox = ListBox(self.event_listwalker)
        self.event_linebox = MyLineBox(self.event_listbox)
        self.event_buttons = button_pile([other_btn(_("View full log"), on_press=self.view_log)])
        event_body = [
            ('pack', Text("")),
            ('weight', 1, Padding.center_79(self.event_linebox)),
            ('pack', Text("")),
            ('pack', self.event_buttons),
            ('pack', Text("")),
        ]
        self.event_pile = Pile(event_body)

        self.log_listwalker = SimpleFocusListWalker([])
        self.log_listbox = ListBox(self.log_listwalker)
        log_linebox = MyLineBox(self.log_listbox, _("Full installer output"))
        log_body = [
            ('weight', 1, log_linebox),
            ('pack', button_pile([other_btn(_("Close"), on_press=self.close_log)])),
            ]
        self.log_pile = Pile(log_body)

        super().__init__(self.event_pile)

    def add_event(self, text):
        at_end = len(self.event_listwalker) == 0 or self.event_listbox.focus_position == len(self.event_listwalker) - 1
        if len(self.event_listwalker) > 0:
            self.event_listwalker[-1] = self.event_listwalker[-1][0]
        self.event_listwalker.append(Columns([('pack', Text(text)), ('pack', self.spinner)], dividechars=1))
        if at_end:
            self.event_listbox.set_focus(len(self.event_listwalker) - 1)
            self.event_listbox.set_focus_valign('bottom')

    def add_log_line(self, text):
        at_end = len(self.log_listwalker) == 0 or self.log_listbox.focus_position == len(self.log_listwalker) - 1
        self.log_listwalker.append(Text(text))
        if at_end:
            self.log_listbox.set_focus(len(self.log_listwalker) - 1)
            self.log_listbox.set_focus_valign('bottom')

    def set_status(self, text):
        self.event_linebox.set_title(text)

    def show_complete(self, include_exit=False):
        p = self.event_buttons.original_widget
        p.contents.append(
            (ok_btn(_("Reboot Now"), on_press=self.reboot), p.options('pack')))
        if include_exit:
            p.contents.append(
                (cancel_btn(_("Exit To Shell"), on_press=self.quit), p.options('pack')))

        w = 0
        for b, o in p.contents:
            w = max(len(b.base_widget.label), w)
        self.event_buttons.width = self.event_buttons.min_width = w + 4
        self.event_pile.focus_position = 3
        p.focus_position = 1

    def reboot(self, btn):
        self.controller.reboot()

    def quit(self, btn):
        self.controller.quit()

    def view_log(self, btn):
        self._w = self.log_pile

    def close_log(self, btn):
        self._w = self.event_pile
