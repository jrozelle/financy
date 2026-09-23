"""Reglages communs a tous les tests."""
import os
import tempfile

import models

# init_db migre aussi la base de demo : pendant les tests, jamais celle du
# depot (fichier versionne), mais un chemin qui n'existe pas.
models.DEMO_DB_PATH = os.path.join(tempfile.gettempdir(), 'financy-tests-demo-absente.db')
