from marketplace_common.observability import install_api_observability

from gateway.app import create_app

app = create_app()
install_api_observability(app, "gateway")
