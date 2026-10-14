"""Pages shown as tabs in the main window, in this order. Add new pages (e.g. the map) here."""

from .diagnostics import DiagnosticsPage
from .gallery import GalleryPage
from .import_page import ImportPage
from .map_page import MapPage
from .overview import OverviewPage
from .timeline import TimelinePage

PAGES = [OverviewPage, TimelinePage, MapPage, GalleryPage, ImportPage, DiagnosticsPage]
