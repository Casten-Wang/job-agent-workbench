"""Use Windows' certificate store without changing global SSL behavior."""

import os
import ssl


def tls_context():
    if os.name == "nt":
        try:
            import truststore
        except ImportError:
            pass
        else:
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()
