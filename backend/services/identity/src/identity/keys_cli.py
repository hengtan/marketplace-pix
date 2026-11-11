from __future__ import annotations

from identity.infrastructure.security.keys import generate_private_pem

if __name__ == "__main__":
    print(generate_private_pem().strip().replace("\n", "\\n"))
