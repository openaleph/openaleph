import logging
import warnings

from sqlalchemy.exc import SAWarning

__version__ = "5.1.0-rc5"

# shut up useless SA warning:
warnings.filterwarnings("ignore", "Unicode type received non-unicode bind param value.")
warnings.filterwarnings("ignore", category=SAWarning)

# specific loggers
logging.getLogger("faker").setLevel(logging.WARNING)
logging.getLogger("rdflib").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("elasticsearch").setLevel(logging.ERROR)
logging.getLogger("redis").setLevel(logging.DEBUG)
logging.getLogger("s3transfer").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("httpstream").setLevel(logging.WARNING)
logging.getLogger("factory").setLevel(logging.WARNING)

# Log all SQL statements:
# logging.getLogger('sqlalchemy.engine').setLevel(log_level)
