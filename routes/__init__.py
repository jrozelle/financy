from .positions import positions_bp
from .flux import flux_bp
from .synthese import synthese_bp
from .entities import entities_bp
from .import_export import import_export_bp
from .referential import referential_bp
from .tools import tools_bp
from .holdings import holdings_bp
from .prices import prices_bp
from .pdf_import import pdf_import_bp
from .advisor import advisor_bp

all_blueprints = [
    positions_bp,
    flux_bp,
    synthese_bp,
    entities_bp,
    import_export_bp,
    referential_bp,
    tools_bp,
    holdings_bp,
    prices_bp,
    pdf_import_bp,
    advisor_bp,
]
