from firebase_functions import https_fn
import firebase_admin

# Initialise Firebase Admin only once
if not firebase_admin._apps:
    firebase_admin.initialize_app()


@https_fn.on_request()
def hello(req: https_fn.Request) -> https_fn.Response:
    # Simple health check function
    return https_fn.Response(
        "Hello from Triparific Firebase Functions 👋",
        mimetype="text/plain",
        status=200,
    )

