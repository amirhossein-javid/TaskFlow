from config.logging import production_logging

bind = "0.0.0.0:8000"
workers = 3
timeout = 30
graceful_timeout = 30
errorlog = "-"
accesslog = "-"
access_log_format = "%(s)s %(M)s"
logconfig_dict = production_logging()
# Django interprets the single, overwritten proxy header. Gunicorn must not trust
# arbitrary forwarded headers or accept SCRIPT_NAME/PATH_INFO from clients.
forwarded_allow_ips = ""
secure_scheme_headers = {}
forwarder_headers = ""
