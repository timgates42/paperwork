import logging
import os
import multiprocessing
import platform
import sys

import pyinsane2
import gettext
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from paperwork.frontend.util import load_uifile
from paperwork.frontend.util.jobs import Job, JobFactory


_ = gettext.gettext
logger = logging.getLogger(__name__)


class JobScannerScanner(Job):
    __gsignals__ = {
        'scan-done': (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    can_stop = False
    priority = 1000

    def __init__(self, factory, id):
        Job.__init__(self, factory, id)

    def do(self):
        # Simply log everything
        try:
            logger.info("====== START OF SYSTEM INFO ======")
            logger.info("os.name: {}".format(os.name))
            logger.info("sys.version: {}".format(sys.version))
            if hasattr(os, 'uname'):
                try:
                    logger.info("os.uname: {}".format(os.uname()))
                except:
                    pass
            try:
                logger.info("platform.architecture: {}".format(
                    platform.architecture()
                ))
                logger.info("platform.platform: {}".format(platform.platform()))
                logger.info("platform.processor: {}".format(
                    platform.processor())
                )
                logger.info("platform.version: {}".format(platform.version()))
                if hasattr(platform, 'linux_distribution'):
                    logger.info("platform.linux_distribution: {}".format(
                        platform.linux_distribution()
                    ))
                if hasattr(platform, 'win32_ver'):
                    logger.info("platform.win32_ver: {}".format(
                        platform.win32_ver()
                    ))
                logger.info("multiprocessing.cpu_count: {}".format(
                    multiprocessing.cpu_count()
                ))
            except Exception as exc:
                logger.exception(exc)
            try:
                mem = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
                logger.info("Available memory: {}".format(mem))
            except Exception as exc:
                logger.exception(exc)
            logger.info("====== END OF SYSTEM INFO ======")

            logger.info("====== START OF SCANNER INFO ======")
            devices = pyinsane2.get_devices()
            logger.info("{} scanners found".format(len(devices)))

            for device in pyinsane2.get_devices():
                logger.info("=== {} ===".format(str(device)))

                for opt in device.options.values():
                    logger.info("Option: {}".format(opt.name))
                    logger.info("  Title: {}".format(opt.title))
                    logger.info("  Desc: {}".format(opt.desc))
                    logger.info("  Type: {}".format(str(opt.val_type)))
                    logger.info("  Unit: {}".format(str(opt.unit)))
                    logger.info("  Size: {}".format(opt.size))
                    logger.info("  Capabilities: {}".format(
                        str(opt.capabilities))
                    )
                    logger.info("  Constraint type: {}".format(
                        str(opt.constraint_type))
                    )
                    logger.info("  Constraint: {}".format(str(opt.constraint)))
                    try:
                        logger.info("  Value: {}".format(str(opt.value)))
                    except pyinsane2.PyinsaneException as exc:
                        # Some scanner allow changing a value, but not reading
                        # it. For instance Canon Lide 110 allow setting the
                        # resolution, but not reading it ...
                        logger.warning("    Value: *FAILED*")
                        logger.exception(exc)

            logger.info("====== END OF SCANNER INFORMATIONS ======")
        except Exception as exc:
            logger.exception(exc)
        finally:
            self.emit('scan-done')


GObject.type_register(JobScannerScanner)


class JobFactoryScannerScanner(JobFactory):

    def __init__(self, diag_win):
        JobFactory.__init__(self, "ScannerScanner")
        self.diag_win = diag_win

    def make(self):
        job = JobScannerScanner(self, next(self.id_generator))
        job.connect(
            'scan-done',
            lambda job: GLib.idle_add(
                self.diag_win.on_scan_done_cb
            )
        )
        return job


class LogTracker(logging.Handler):
    def __init__(self):
        super(LogTracker, self).__init__()
        self._formatter = logging.Formatter(
            '%(levelname)-6s %(name)-30s %(message)s'
        )
        self.output = []

    def emit(self, record):
        line = self._formatter.format(record)
        self.output.append(line)

    def get_logs(self):
        return "\n".join(self.output)

    @staticmethod
    def init():
        logger = logging.getLogger()
        handler = logging.StreamHandler()
        handler.setFormatter(g_log_tracker._formatter)
        logger.addHandler(handler)
        logger.addHandler(g_log_tracker)
        logger.setLevel({
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }[os.getenv("PAPERWORK_VERBOSE", "INFO")])


g_log_tracker = LogTracker()


class DiagDialog(object):
    def __init__(self, main_win):
        widget_tree = load_uifile(
            os.path.join("diag", "diagdialog.glade"))

        self.buf = widget_tree.get_object("textbufferDiag")

        self.dialog = widget_tree.get_object("dialogDiag")
        self.dialog.set_transient_for(main_win.window)
        self.dialog.connect("response", self.on_response_cb)

        self.scrollwin = widget_tree.get_object("scrolledwindowDiag")

        self._main_win = main_win

        self.set_text(_("Loading ..."))

        txt_view = widget_tree.get_object("textviewDiag")
        txt_view.connect("size-allocate", self.scroll_to_bottom)

        scheduler = main_win.schedulers['main']
        factory = JobFactoryScannerScanner(self)
        job = factory.make()
        scheduler.schedule(job)

    def set_text(self, txt):
        self.buf.set_text(txt, -1)
        GLib.idle_add(self.scroll_to_bottom)

    def scroll_to_bottom(self, *args, **kwargs):
        vadj = self.scrollwin.get_vadjustment()
        vadj.set_value(vadj.get_upper())

    def on_scan_done_cb(self):
        self.set_text(g_log_tracker.get_logs())

    def on_response_cb(self, widget, response):
        if response == 0:  # close
            self.dialog.set_visible(False)
            self.dialog.destroy()
            self.dialog = None
            return True
        if response == 1:  # save as
            chooser = Gtk.FileChooserDialog(
                title=_("Save as"),
                transient_for=self._main_win.window,
                action=Gtk.FileChooserAction.SAVE
            )
            file_filter = Gtk.FileFilter()
            file_filter.set_name("text")
            file_filter.add_mime_type("text/plain")
            chooser.add_filter(file_filter)
            chooser.add_buttons(Gtk.STOCK_CANCEL,
                                Gtk.ResponseType.CANCEL,
                                Gtk.STOCK_SAVE,
                                Gtk.ResponseType.OK)
            response = chooser.run()
            try:
                if response != Gtk.ResponseType.OK:
                    return True

                filepath = chooser.get_filename()
                with open(filepath, "w") as fd:
                    start = self.buf.get_iter_at_offset(0)
                    end = self.buf.get_iter_at_offset(-1)
                    text = self.buf.get_text(start, end, False)
                    fd.write(text)
            finally:
                chooser.set_visible(False)
                chooser.destroy()

            return True
        if response == 2:  # copy
            gdk_win = self._main_win.window.get_window()
            clipboard = Gtk.Clipboard.get_default(gdk_win.get_display())
            start = self.buf.get_iter_at_offset(0)
            end = self.buf.get_iter_at_offset(-1)
            text = self.buf.get_text(start, end, False)
            clipboard.set_text(text, -1)
            return True

    def show(self):
        self.dialog.set_visible(True)
