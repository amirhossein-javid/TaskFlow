bind = "0.0.0.0:8000"
workers = 3
timeout = 30
graceful_timeout = 30
errorlog = "-"
# Nginx owns access logs. Avoid duplicating paths containing invitation/reset tokens.
accesslog = None
# Django interprets the single, overwritten proxy header. Gunicorn must not trust
# arbitrary forwarded headers or accept SCRIPT_NAME/PATH_INFO from clients.
forwarded_allow_ips = ""
secure_scheme_headers = {}
forwarder_headers = ""
