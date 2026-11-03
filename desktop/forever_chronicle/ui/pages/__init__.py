"""Pages of the main window. MAIN_PAGES get a tab at the bottom, in this order (the first one is shown at start);
MENU_PAGES are opened from the gear menu next to the tabs. Add new pages here."""

from .cinema import CinemaPage
from .diagnostics import DiagnosticsPage
from .gallery import GalleryPage
from .home import HomePage
from .import_page import ImportPage
from .overview import OverviewPage
from .professions import ProfessionsPage
from .settings import SettingsPage
from .timeline import TimelinePage

MAIN_PAGES = [HomePage, OverviewPage, TimelinePage, GalleryPage, CinemaPage, ProfessionsPage]
MENU_PAGES = [ImportPage, SettingsPage, DiagnosticsPage]
