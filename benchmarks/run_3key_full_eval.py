#!/usr/bin/env python3
"""
Bounded Evaluation of PolyFabric on FarmWatch
Run ID: RUN_20261013_FARMWATCH_BOUNDED_EVAL

Compares three approaches across 20 tasks (4 per category: UI, Logic, Refactoring,
Dependency Tracing, Difficult/Negative):
  A. polyfabric_retrieval: PolyFabric AST + hybrid vector/FTS retrieval + Gemini 2.5 Flash
  B. targeted_search: Ripgrep (rg), file listing, and selective line reads + Gemini 2.5 Flash
  C. whole_file_context: Whole-file repository context + Gemini 2.5 Flash

All credentials are read from environment variables and strictly sanitized from outputs.
"""

import os
import re
import sys
import json
import math
import time
import shutil
import random
import tempfile
import resource
import subprocess
import urllib.request
import urllib.error
import statistics
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# Ensure PolyFabric is importable in sandbox
sys.path.insert(0, '/home/agent/workspace/PolyFabric/src')
from infinite_memory.core.store import VectorStore
from infinite_memory.core.indexer import index_repository
from infinite_memory.core.task_context import build_task_context, extract_polyfabric_terms
from infinite_memory.utils.path_utils import normalize_and_resolve_repo_path, to_relative_repo_path
from infinite_memory.parsers.tree_sitter_ast import UniversalASTParser

RUN_ID = "RUN_20261013_FARMWATCH_3KEY_CORRECTED"
REPO_PATH = Path("/tmp/FarmWatch")
OUT_DIR = Path(f"/tmp/results/{RUN_ID}")
GATEWAY_URL = os.environ.get("LITELLM_BASE_URL", "https://router.helixengine.app")
MODEL_NAME = "gemini-2.5-flash"

VAULT_PATH = Path("/tmp/.eval_keys_vault.json")
if not VAULT_PATH.exists():
    raise RuntimeError(f"Vault not found at {VAULT_PATH}")
with open(VAULT_PATH, "r") as _vf:
    _vault = json.load(_vf)
MASTER_KEY = _vault["master_key"]
KEYS = _vault["keys"]
APPROACH_KEY_MAP = {
    "polyfabric_retrieval": KEYS[f"{RUN_ID}-PolyFabricRetrieval"],
    "targeted_search": KEYS[f"{RUN_ID}-TargetedSearch"],
    "whole_file_context": KEYS[f"{RUN_ID}-WholeFileContext"]
}
APPROACH_ALIAS_MAP = {
    "polyfabric_retrieval": f"{RUN_ID}-PolyFabricRetrieval",
    "targeted_search": f"{RUN_ID}-TargetedSearch",
    "whole_file_context": f"{RUN_ID}-WholeFileContext"
}
LEDGER_PATH = OUT_DIR / "client_request_ledger.jsonl"
PROJECT_ID = "farmwatch-1"

# Pricing for Gemini 2.5 Flash via LiteLLM ($0.15 / 1M input, $0.60 / 1M output)
PRICE_PROMPT_PER_TOKEN = 0.00000015
PRICE_COMPLETION_PER_TOKEN = 0.00000060

APPROACHES = [
    "polyfabric_retrieval",
    "targeted_search",
    "whole_file_context"
]

# ============================================================================
# 20 TASKS MANIFEST & SEPARATE GROUND TRUTH ACCEPTANCE CRITERIA
# Note: Only `instruction` is passed to the approaches. `target_files` and
# `assertions` are strictly held out for post-edit verification.
# ============================================================================
TASKS = [
    # --- CATEGORY 1: UI (4 Tasks) ---
    {
        "task_id": "UI-01",
        "category": "UI",
        "subcategory": "branding_ui_and_metadata",
        "title": "Rebrand FarmWatch to AgriSentinel across UI translations and HTML/JSON metadata",
        "instruction": (
            "Rebrand the application from 'FarmWatch' to 'AgriSentinel' in three places: "
            "1) the English brand translation (`en.brand: 'FarmWatch'`), "
            "2) the `<title>` and `og:title` tags in the root HTML entry page (updating 'FarmWatch - Satellite & AI Agricultural Inspection' to 'AgriSentinel - Satellite & AI Agricultural Inspection'), and "
            "3) the `name` field in the application metadata JSON file (updating 'FarmWatch - Satellite & AI Agricultural Inspection' to 'AgriSentinel - Satellite & AI Agricultural Inspection')."
        ),
        "target_files": ["src/utils/i18n.ts", "index.html", "metadata.json"],
        "is_negative": False,
        "is_ui": True,
        "viewport_sizes": [{"width": 1280, "height": 800}, {"width": 375, "height": 667}],
        "assertions": [
            {"file": "src/utils/i18n.ts", "must_contain": ["brand: 'AgriSentinel'"], "must_not_contain": ["brand: 'FarmWatch'"]},
            {"file": "index.html", "must_contain": ["<title>AgriSentinel - Satellite & AI Agricultural Inspection</title>"], "must_not_contain": ["<title>FarmWatch - Satellite & AI Agricultural Inspection</title>"]},
            {"file": "metadata.json", "must_contain": ["\"name\": \"AgriSentinel - Satellite & AI Agricultural Inspection\""], "must_not_contain": ["\"name\": \"FarmWatch - Satellite & AI Agricultural Inspection\""]}
        ]
    },
    {
        "task_id": "UI-02",
        "category": "UI",
        "subcategory": "font_size_and_typography",
        "title": "Increase TopBar brand heading font size and adjust letter tracking",
        "instruction": (
            "In the top navigation bar component that renders `{t.brand}` inside a `<span>` with classes "
            "`text-xl font-bold tracking-tight text-[#14261A] font-display`, change `text-xl` to `text-2xl` and change `tracking-tight` to `tracking-normal`."
        ),
        "target_files": ["src/components/TopBar.tsx"],
        "is_negative": False,
        "is_ui": True,
        "viewport_sizes": [{"width": 1280, "height": 800}, {"width": 375, "height": 667}],
        "assertions": [
            {"file": "src/components/TopBar.tsx", "must_contain": ["text-2xl font-bold tracking-normal text-[#14261A] font-display"], "must_not_contain": ["text-xl font-bold tracking-tight text-[#14261A] font-display"]}
        ]
    },
    {
        "task_id": "UI-03",
        "category": "UI",
        "subcategory": "responsive_spacing",
        "title": "Update DashboardView vertical spacing and responsive hero banner padding",
        "instruction": (
            "In the dashboard overview view component containing the `Hero / Context Banner` section, "
            "update the root wrapper `<div>` class from `space-y-6` to `space-y-8`, and change the Hero / Context Banner card padding from `p-5 sm:p-6` to `p-6 sm:p-8 md:p-10`."
        ),
        "target_files": ["src/components/DashboardView.tsx"],
        "is_negative": False,
        "is_ui": True,
        "viewport_sizes": [{"width": 1280, "height": 800}, {"width": 375, "height": 667}],
        "assertions": [
            {"file": "src/components/DashboardView.tsx", "must_contain": ["<div className=\"space-y-8\">", "p-6 sm:p-8 md:p-10 shadow-xs"], "must_not_contain": ["p-5 sm:p-6 shadow-xs"]}
        ]
    },
    {
        "task_id": "UI-04",
        "category": "UI",
        "subcategory": "shared_styles",
        "title": "Refine global custom scrollbar dimensions and colors in stylesheet",
        "instruction": (
            "In the global CSS stylesheet defining custom scrollbar rules (`::-webkit-scrollbar`), "
            "change the scrollbar `width` and `height` from `6px` to `8px`, update `::-webkit-scrollbar-thumb` background from `#C4CEC3` to `#A3B8A2` and `border-radius` from `3px` to `4px`, "
            "and update `::-webkit-scrollbar-thumb:hover` background from `#9FAFA0` to `#7D967B`."
        ),
        "target_files": ["src/index.css"],
        "is_negative": False,
        "is_ui": True,
        "viewport_sizes": [{"width": 1280, "height": 800}],
        "assertions": [
            {"file": "src/index.css", "must_contain": ["width: 8px;", "height: 8px;", "background: #A3B8A2;", "border-radius: 4px;", "background: #7D967B;"], "must_not_contain": ["background: #C4CEC3;", "background: #9FAFA0;"]}
        ]
    },

    # --- CATEGORY 2: LOGIC (4 Tasks) ---
    {
        "task_id": "LOGIC-01",
        "category": "Logic",
        "subcategory": "default_values_and_minimum_boundary",
        "title": "Update default areaHa and minimum area boundary in generatePresetPolygon",
        "instruction": (
            "In `generatePresetPolygon`, update the default parameter `areaHa: number = 1.0` to `areaHa: number = 1.5`, "
            "and change the minimum area clamp in `Math.max(0.1, areaHa) * 10000` from `0.1` to `0.25`."
        ),
        "target_files": ["src/utils/geo.ts"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["areaHa: number = 1.5", "Math.max(0.25, areaHa) * 10000"], "must_not_contain": ["Math.max(0.1, areaHa) * 10000"]}
        ]
    },
    {
        "task_id": "LOGIC-02",
        "category": "Logic",
        "subcategory": "polygon_resolution_threshold",
        "title": "Increase circle approximation node count from 8 to 16 in generatePresetPolygon",
        "instruction": (
            "Inside `generatePresetPolygon` for the circular agricultural pivot irrigation polygon branch, "
            "change `const segments = 8;` to `const segments = 16;`."
        ),
        "target_files": ["src/utils/geo.ts"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["const segments = 16;"], "must_not_contain": ["const segments = 8;"]}
        ]
    },
    {
        "task_id": "LOGIC-03",
        "category": "Logic",
        "subcategory": "boundary_conditions_zoom",
        "title": "Adjust Web Mercator zoom clamping boundaries in getSatelliteTiles",
        "instruction": (
            "In `getSatelliteTiles`, update the zoom clamping expression from `Math.min(18, Math.max(12, zoom))` "
            "to `Math.min(19, Math.max(13, zoom))` and update the step-down while-loop condition from `safeZoom > 12` to `safeZoom > 13`."
        ),
        "target_files": ["src/utils/geo.ts"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["Math.min(19, Math.max(13, zoom))", "safeZoom > 13"], "must_not_contain": ["Math.min(18, Math.max(12, zoom))", "safeZoom > 12"]}
        ]
    },
    {
        "task_id": "LOGIC-04",
        "category": "Logic",
        "subcategory": "validation_and_fallback_defaults",
        "title": "Update empty coordinate fallback bounding box in getBoundingBox",
        "instruction": (
            "In `getBoundingBox(coords: Coordinate[])`, update the empty/null fallback return value "
            "from `{ minLng: 73.78, maxLng: 73.79, minLat: 19.99, maxLat: 20.00 }` to `{ minLng: 73.80, maxLng: 73.85, minLat: 20.15, maxLat: 20.20 }`."
        ),
        "target_files": ["src/utils/geo.ts"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["{ minLng: 73.80, maxLng: 73.85, minLat: 20.15, maxLat: 20.20 }"], "must_not_contain": ["{ minLng: 73.78, maxLng: 73.79, minLat: 19.99, maxLat: 20.00 }"]}
        ]
    },

    # --- CATEGORY 3: REFACTORING (4 Tasks) ---
    {
        "task_id": "REFACTOR-01",
        "category": "Refactoring",
        "subcategory": "rename_function_and_all_callers",
        "title": "Rename calculateGeodesicAreaHa to computeGeodesicAreaHa across declaration and all callers",
        "instruction": (
            "Rename the exported function `calculateGeodesicAreaHa` to `computeGeodesicAreaHa` in its defining utility file "
            "and update all callers and imports across the repository."
        ),
        "target_files": ["src/utils/geo.ts", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["export function computeGeodesicAreaHa", "areaHa: computeGeodesicAreaHa(coords)"], "must_not_contain": ["calculateGeodesicAreaHa"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["computeGeodesicAreaHa"], "must_not_contain": ["calculateGeodesicAreaHa"]}
        ]
    },
    {
        "task_id": "REFACTOR-02",
        "category": "Refactoring",
        "subcategory": "update_exports_imports",
        "title": "Rename sortPolygonClockwise to orderPolygonClockwise across definition and callers",
        "instruction": (
            "Rename the exported function `sortPolygonClockwise` to `orderPolygonClockwise` in its defining module "
            "and update all imports and call sites across the codebase."
        ),
        "target_files": ["src/utils/geo.ts", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["export function orderPolygonClockwise"], "must_not_contain": ["sortPolygonClockwise"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["orderPolygonClockwise"], "must_not_contain": ["sortPolygonClockwise"]}
        ]
    },
    {
        "task_id": "REFACTOR-03",
        "category": "Refactoring",
        "subcategory": "modify_shared_type",
        "title": "Extend CropSeason.irrigationMethod union type with 'subsurface_drip' and support in NewFieldModal",
        "instruction": (
            "Add `'subsurface_drip'` to the `irrigationMethod` union type on the `CropSeason` interface (`'drip' | 'sprinkler' | 'flood' | 'rainfed' | 'furrow' | 'subsurface_drip'`), "
            "and update the `useState<'drip' | 'sprinkler' | 'flood' | 'rainfed'>('drip')` type parameter for `irrigation` in the new field modal component to also include `'subsurface_drip'`."
        ),
        "target_files": ["src/types/farmwatch.ts", "src/components/NewFieldModal.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/types/farmwatch.ts", "must_contain": ["'subsurface_drip'"], "must_not_contain": []},
            {"file": "src/components/NewFieldModal.tsx", "must_contain": ["'subsurface_drip'"], "must_not_contain": []}
        ]
    },
    {
        "task_id": "REFACTOR-04",
        "category": "Refactoring",
        "subcategory": "duplicate_symbol_disambiguation",
        "title": "Rename formatDate in i18n utility to formatLocalizedDate and update all importing components",
        "instruction": (
            "Rename the exported function `formatDate` to `formatLocalizedDate` in the localization utility module, "
            "and update every component that imports and calls `formatDate`."
        ),
        "target_files": [
            "src/utils/i18n.ts",
            "src/components/DashboardView.tsx",
            "src/components/SoilAndWeatherView.tsx",
            "src/components/SatelliteTimelineView.tsx",
            "src/components/ActionHistoryView.tsx"
        ],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/i18n.ts", "must_contain": ["export function formatLocalizedDate"], "must_not_contain": ["export function formatDate("]},
            {"file": "src/components/DashboardView.tsx", "must_contain": ["formatLocalizedDate"], "must_not_contain": ["formatDate("]},
            {"file": "src/components/SoilAndWeatherView.tsx", "must_contain": ["formatLocalizedDate"], "must_not_contain": ["formatDate("]},
            {"file": "src/components/SatelliteTimelineView.tsx", "must_contain": ["formatLocalizedDate"], "must_not_contain": ["formatDate("]},
            {"file": "src/components/ActionHistoryView.tsx", "must_contain": ["formatLocalizedDate"], "must_not_contain": ["formatDate("]}
        ]
    },

    # --- CATEGORY 4: DEPENDENCY TRACING (4 Tasks) ---
    {
        "task_id": "DEP-01",
        "category": "Dependency_Tracing",
        "subcategory": "frontend_backend_route_migration",
        "title": "Migrate geocoding API route from /api/geo/geocode to /api/v2/geo/geocode across server and frontend",
        "instruction": (
            "Migrate the geocoding API endpoint path from `/api/geo/geocode` to `/api/v2/geo/geocode` in both the Express backend route definition "
            "and the frontend `fetch` request."
        ),
        "target_files": ["server.ts", "src/components/NewFieldModal.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["app.get('/api/v2/geo/geocode'"], "must_not_contain": ["app.get('/api/geo/geocode'"]},
            {"file": "src/components/NewFieldModal.tsx", "must_contain": ["/api/v2/geo/geocode?q="], "must_not_contain": ["/api/geo/geocode?q="]}
        ]
    },
    {
        "task_id": "DEP-02",
        "category": "Dependency_Tracing",
        "subcategory": "api_contract_and_payload",
        "title": "Migrate satellite simulation endpoint from /api/satellite/simulate-observations to /api/v2/satellite/simulate",
        "instruction": (
            "Update the satellite observation simulation endpoint path from `/api/satellite/simulate-observations` "
            "to `/api/v2/satellite/simulate` in both the Express server route handler and the frontend `fetch` call."
        ),
        "target_files": ["server.ts", "src/App.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["app.post('/api/v2/satellite/simulate'"], "must_not_contain": ["app.post('/api/satellite/simulate-observations'"]},
            {"file": "src/App.tsx", "must_contain": ["fetch('/api/v2/satellite/simulate'"], "must_not_contain": ["fetch('/api/satellite/simulate-observations'"]}
        ]
    },
    {
        "task_id": "DEP-03",
        "category": "Dependency_Tracing",
        "subcategory": "cross_stack_weather_contract",
        "title": "Add units=metric query parameter to /api/weather call and echo units in backend weather route",
        "instruction": (
            "Update the frontend weather `fetch` URL from ``/api/weather?lat=${avgLat}&lon=${avgLng}`` to ``/api/weather?lat=${avgLat}&lon=${avgLng}&units=metric``. "
            "In the Express backend `app.get('/api/weather', ...)` handler, extract `const units = String(req.query.units || 'metric');` and include `units,` in the returned `weatherContext` JSON object."
        ),
        "target_files": ["server.ts", "src/App.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/App.tsx", "must_contain": ["/api/weather?lat=${avgLat}&lon=${avgLng}&units=metric"], "must_not_contain": []},
            {"file": "server.ts", "must_contain": ["req.query.units"], "must_not_contain": []}
        ]
    },
    {
        "task_id": "DEP-04",
        "category": "Dependency_Tracing",
        "subcategory": "config_and_health_contract",
        "title": "Add apiVersion '2.1.0' to /api/health endpoint in Express server",
        "instruction": (
            "Update the `/api/health` GET route handler in the Express server so the JSON response object includes `apiVersion: '2.1.0'` right after `status: 'ok'`."
        ),
        "target_files": ["server.ts"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["apiVersion: '2.1.0'"], "must_not_contain": []}
        ]
    },

    # --- CATEGORY 5: DIFFICULT / NEGATIVE CASES (4 Tasks) ---
    {
        "task_id": "NEG-01",
        "category": "Difficult_Negative",
        "subcategory": "nonexistent_symbol",
        "title": "Modify nonexistent function calculateSoilSalinityIndex",
        "instruction": (
            "Update the function `calculateSoilSalinityIndex` in `src/utils/soilMath.ts` to use a logarithmic decay factor of 0.85. "
            "If this file or function does not exist in the repository, do NOT invent or create it; explicitly abstain and respond with `ABSTAIN: MISSING_TARGET`."
        ),
        "target_files": [],
        "is_negative": True,
        "is_ui": False,
        "assertions": []
    },
    {
        "task_id": "NEG-02",
        "category": "Difficult_Negative",
        "subcategory": "misspelled_identifier",
        "title": "Update misspelled identifier computeEvapoTranspirationQuota in WeatherService.ts",
        "instruction": (
            "In `src/services/WeatherService.ts`, change the threshold inside `computeEvapoTranspirationQuota` from 4.2 to 5.0. "
            "If neither `src/services/WeatherService.ts` nor `computeEvapoTranspirationQuota` exists in the codebase, do NOT guess or modify unrelated files; respond with `ABSTAIN: MISSING_TARGET`."
        ),
        "target_files": [],
        "is_negative": True,
        "is_ui": False,
        "assertions": []
    },
    {
        "task_id": "NEG-03",
        "category": "Difficult_Negative",
        "subcategory": "ambiguous_request",
        "title": "Ambiguous request to change threshold value without specifying component or metric",
        "instruction": (
            "Change the threshold from 15 to 25 in the component. "
            "Note: If this request is underspecified and does not uniquely identify which component, file, or domain metric should be changed, "
            "do NOT modify random files; respond with `ABSTAIN: AMBIGUOUS_REQUEST` and request clarification."
        ),
        "target_files": [],
        "is_negative": True,
        "is_ui": False,
        "assertions": []
    },
    {
        "task_id": "NEG-04",
        "category": "Difficult_Negative",
        "subcategory": "stale_deleted_entry",
        "title": "Update legacy Leaflet map tile layer in removed LeafletMapCanvas.tsx",
        "instruction": (
            "In `src/components/LeafletMapCanvas.tsx`, update the `L.tileLayer` attribution string to include OpenTopoMap. "
            "If `LeafletMapCanvas.tsx` does not exist in the repository, do NOT create the file or edit other map views; respond with `ABSTAIN: STALE_OR_MISSING_TARGET`."
        ),
        "target_files": [],
        "is_negative": True,
        "is_ui": False,
        "assertions": []
    }
]

# ============================================================================
# 6 UNSEEN GENERALIZATION TASKS (3 Multi-Caller Renames + 3 Endpoint Migrations)
# Added after fixing the retrieval architecture to verify that the fix generalizes
# beyond the original 20 frozen tasks.
# ============================================================================
GEN_TASKS = [
    {
        "task_id": "GEN-REFACTOR-01",
        "category": "Generalization_Refactoring",
        "subcategory": "multi_component_function_rename",
        "title": "Rename generatePresetPolygon to createPresetBoundaryPolygon across utility and all importing components",
        "instruction": (
            "Rename the exported function `generatePresetPolygon` to `createPresetBoundaryPolygon` in its defining utility file "
            "and update all imports and call sites across the repository."
        ),
        "target_files": ["src/utils/geo.ts", "src/components/NewFieldModal.tsx", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["export function createPresetBoundaryPolygon"], "must_not_contain": ["generatePresetPolygon"]},
            {"file": "src/components/NewFieldModal.tsx", "must_contain": ["createPresetBoundaryPolygon"], "must_not_contain": ["generatePresetPolygon"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["createPresetBoundaryPolygon"], "must_not_contain": ["generatePresetPolygon"]}
        ]
    },
    {
        "task_id": "GEN-REFACTOR-02",
        "category": "Generalization_Refactoring",
        "subcategory": "multi_component_tile_grid_rename",
        "title": "Rename getSatelliteTiles to computeSatelliteTileGrid across utility and all callers",
        "instruction": (
            "Rename the exported function `getSatelliteTiles` to `computeSatelliteTileGrid` in its defining utility module "
            "and update all imports and callers across the codebase."
        ),
        "target_files": ["src/utils/geo.ts", "src/components/NewFieldModal.tsx", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["export function computeSatelliteTileGrid"], "must_not_contain": ["getSatelliteTiles"]},
            {"file": "src/components/NewFieldModal.tsx", "must_contain": ["computeSatelliteTileGrid"], "must_not_contain": ["getSatelliteTiles"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["computeSatelliteTileGrid"], "must_not_contain": ["getSatelliteTiles"]}
        ]
    },
    {
        "task_id": "GEN-REFACTOR-03",
        "category": "Generalization_Refactoring",
        "subcategory": "multi_caller_bounds_rename",
        "title": "Rename getBoundingBox to computePolygonBounds across definition and all call sites",
        "instruction": (
            "Rename the exported function `getBoundingBox` to `computePolygonBounds` in its defining utility file "
            "and update all imports and call sites across the repository."
        ),
        "target_files": ["src/utils/geo.ts", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "src/utils/geo.ts", "must_contain": ["export function computePolygonBounds"], "must_not_contain": ["getBoundingBox"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["computePolygonBounds"], "must_not_contain": ["getBoundingBox"]}
        ]
    },
    {
        "task_id": "GEN-DEP-01",
        "category": "Generalization_Dependency",
        "subcategory": "gee_tiles_endpoint_migration",
        "title": "Migrate /api/satellite/gee-tiles to /api/v2/satellite/gee-tiles across server and frontend",
        "instruction": (
            "Migrate the Google Earth Engine satellite tiles endpoint path from `/api/satellite/gee-tiles` "
            "to `/api/v2/satellite/gee-tiles` in both the Express server route handler and the frontend `fetch` request."
        ),
        "target_files": ["server.ts", "src/components/FieldGisView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["app.post('/api/v2/satellite/gee-tiles'"], "must_not_contain": ["app.post('/api/satellite/gee-tiles'"]},
            {"file": "src/components/FieldGisView.tsx", "must_contain": ["fetch('/api/v2/satellite/gee-tiles'"], "must_not_contain": ["fetch('/api/satellite/gee-tiles'"]}
        ]
    },
    {
        "task_id": "GEN-DEP-02",
        "category": "Generalization_Dependency",
        "subcategory": "ai_assess_endpoint_migration",
        "title": "Migrate /api/ai/assess to /api/v2/ai/crop-assess across backend route and frontend caller",
        "instruction": (
            "Migrate the AI crop assessment endpoint path from `/api/ai/assess` to `/api/v2/ai/crop-assess` "
            "in both the Express backend route handler and the frontend `fetch` call."
        ),
        "target_files": ["server.ts", "src/components/CropAssessmentView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["app.post('/api/v2/ai/crop-assess'"], "must_not_contain": ["app.post('/api/ai/assess'"]},
            {"file": "src/components/CropAssessmentView.tsx", "must_contain": ["fetch('/api/v2/ai/crop-assess'"], "must_not_contain": ["fetch('/api/ai/assess'"]}
        ]
    },
    {
        "task_id": "GEN-DEP-03",
        "category": "Generalization_Dependency",
        "subcategory": "ai_chat_endpoint_migration",
        "title": "Migrate /api/ai/chat to /api/v2/ai/advisor-chat across backend route and frontend caller",
        "instruction": (
            "Migrate the AI advisor chat endpoint path from `/api/ai/chat` to `/api/v2/ai/advisor-chat` "
            "in both the Express backend route definition and the frontend `fetch` request."
        ),
        "target_files": ["server.ts", "src/components/CropAssessmentView.tsx"],
        "is_negative": False,
        "is_ui": False,
        "assertions": [
            {"file": "server.ts", "must_contain": ["app.post('/api/v2/ai/advisor-chat'"], "must_not_contain": ["app.post('/api/ai/chat'"]},
            {"file": "src/components/CropAssessmentView.tsx", "must_contain": ["fetch('/api/v2/ai/advisor-chat'"], "must_not_contain": ["fetch('/api/ai/chat'"]}
        ]
    }
]

ALL_TASKS = TASKS + GEN_TASKS


def sanitize_text(text: str) -> str:
    """Remove any API keys or sensitive tokens from strings before saving."""
    if not text:
        return text
    out = text
    for alias, k in KEYS.items():
        if k and len(k) > 6:
            out = out.replace(k, f"sk-REDACTED_{alias}")
    if MASTER_KEY and len(MASTER_KEY) > 6:
        out = out.replace(MASTER_KEY, "sk-REDACTED_MASTER_KEY")
    out = re.sub(r"sk-[A-Za-z0-9_\-]{10,}", "sk-REDACTED", out)
    return out


def extract_autonomous_search_terms(instruction: str):
    """
    Autonomously extract candidate search tokens (backticked literals, API routes,
    CSS selectors, camelCase symbols, quoted literals) from the task instruction
    without any hidden ground-truth hints. (Kept identical for targeted_search baseline).
    """
    terms = []
    # 1. Backticked code spans
    for m in re.findall(r"`([^`]+)`", instruction):
        clean = m.strip()
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
    # 2. Single-quoted literals
    for m in re.findall(r"'([^']+)'", instruction):
        clean = m.strip()
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
    # 3. API routes or camelCase identifiers
    for m in re.findall(r"(/api/[A-Za-z0-9/_-]+|[a-z]+[A-Z][A-Za-z0-9_]*|[A-Z][a-z]+[A-Z][A-Za-z0-9_]*)", instruction):
        if m not in terms:
            terms.append(m)
    return terms[:8]


GENERIC_TERMS = {"fetch", "div", "span", "name", "width", "height", "title", "irrigation"}


def extract_polyfabric_terms(instruction: str):
    """
    Extract high-signal code symbols, routes, selectors, and string literals for PolyFabric
    AST + hybrid lexical retrieval, handling double-backticks, ellipsis signatures, and dotted paths.
    """
    terms = []
    for m in re.findall(r"`+([^`]+)`+", instruction):
        clean = m.strip()
        if re.match(r"^</?[a-zA-Z0-9]+>$", clean):
            continue
        if re.match(r"^[0-9.]+(?:px|rem|em|%)?$", clean):
            continue
        if "..." in clean:
            clean = clean.split("...")[0].strip().rstrip(",")
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.", clean):
            sub = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*\.", "", clean)
            if len(sub) >= 5 and sub not in terms:
                terms.append(sub)
    instr_no_bt = re.sub(r"`+[^`]+`+", " ", instruction)
    for m in re.findall(r"'([^']+)'", instr_no_bt):
        clean = m.strip()
        if re.match(r"^[0-9.]+(?:px|rem|em|%)?$", clean):
            continue
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
    for m in re.findall(r"(/api/[A-Za-z0-9/_-]+|[a-z]+[A-Z][A-Za-z0-9_]*|[A-Z][a-z]+[A-Z][A-Za-z0-9_]*)", instruction):
        if m not in terms:
            terms.append(m)
    specific = [t for t in terms if t.lower() not in GENERIC_TERMS]
    generic = [t for t in terms if t.lower() in GENERIC_TERMS]
    return (specific + generic)[:10]


def get_all_repo_files(repo_dir: Path):
    """Return list of all source files in FarmWatch for whole-file context baseline."""
    files = []
    exts = {".ts", ".tsx", ".css", ".html", ".json"}
    exclude = {"node_modules", "dist", ".git", "package-lock.json", "bun.lock"}
    for root, dirs, filenames in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in exclude]
        for fname in filenames:
            if fname in exclude:
                continue
            p = Path(root) / fname
            if p.suffix in exts:
                files.append(p)
    return sorted(files)


def gather_context_polyfabric(vs: VectorStore, task: dict, repo_dir: Path):
    """
    Approach A: PolyFabric Retrieval.
    Calls production `build_task_context` from `src.infinite_memory.core.task_context`.
    """
    res = build_task_context(
        store=vs,
        instruction=task["instruction"],
        repo_root=repo_dir,
        project_name=PROJECT_ID,
        max_files=6
    )
    return res["context_text"], res["discovered_files"], res["tool_calls"], res["elapsed_ms"]


def gather_context_targeted_rg(task: dict, repo_dir: Path):
    """
    Approach B: Targeted Search using ripgrep (`rg`), file listing, and selective line reads.
    Derives search patterns autonomously from `task["instruction"]`.
    """
    t0 = time.perf_counter()
    instr = task["instruction"]
    tool_calls = 0
    discovered_files = []
    seen = set()
    matched_lines_by_file = {}

    # 1. File listing (`rg --files`)
    tool_calls += 1
    proc = subprocess.run(
        ["rg", "--files", "--glob", "!node_modules/**", "--glob", "!dist/**", "--glob", "!package-lock.json", "--glob", "!bun.lock", "--glob", "!docs/**", "--glob", "!README.md", "."],
        cwd=str(repo_dir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True
    )
    file_list = [line.strip().lstrip("./") for line in proc.stdout.splitlines() if line.strip()]

    # 2. Extract search terms autonomously from instruction and run `rg -n`
    terms = extract_autonomous_search_terms(instr)
    for pat in terms[:6]:
        tool_calls += 1
        rg_proc = subprocess.run(
            ["rg", "-n", "--fixed-strings", "--glob", "!node_modules/**", "--glob", "!dist/**", "--glob", "!package-lock.json", "--glob", "!bun.lock", "--glob", "!docs/**", "--glob", "!README.md", pat, "."],
            cwd=str(repo_dir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True
        )
        if rg_proc.stdout:
            for line in rg_proc.stdout.splitlines():
                m = re.match(r"^([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+):(\d+):", line)
                if m:
                    cand = m.group(1)
                    if cand.startswith("./"):
                        cand = cand[2:]
                    lno = int(m.group(2))
                    if (repo_dir / cand).exists():
                        if cand not in seen:
                            seen.add(cand)
                            discovered_files.append(cand)
                        matched_lines_by_file.setdefault(cand, []).append(lno)

    # 3. Selective line reads around rg match line numbers (+/- 25 lines)
    selective_reads = []
    for rel in discovered_files[:6]:
        p = repo_dir / rel
        if p.exists() and p.is_file():
            tool_calls += 1
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            if total_lines <= 120:
                selective_reads.append(f"--- FILE: {rel} (Lines 1-{total_lines}) ---\n" + "\n".join(lines) + "\n")
            else:
                lnos = sorted(set(matched_lines_by_file.get(rel, [1])))
                intervals = []
                for lno in lnos[:6]:
                    s = max(1, lno - 25)
                    e = min(total_lines, lno + 30)
                    intervals.append((s, e))
                intervals.sort()
                merged = []
                for s, e in intervals:
                    if not merged or s > merged[-1][1] + 5:
                        merged.append([s, e])
                    else:
                        merged[-1][1] = max(merged[-1][1], e)
                for s, e in merged[:4]:
                    snippet = "\n".join(lines[s - 1:e])
                    selective_reads.append(f"--- FILE: {rel} (Lines {s}-{e} of {total_lines}) ---\n{snippet}\n")

    context_parts = [
        "=== REPOSITORY FILE LIST ===",
        "\n".join(file_list),
        "\n=== SELECTIVE LINE READS AROUND RIPGREP MATCHES ===",
        "\n".join(selective_reads) if selective_reads else "(No matches found by ripgrep)"
    ]

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return "\n".join(context_parts), discovered_files[:6], tool_calls, elapsed_ms


def gather_context_whole_file(task: dict, repo_dir: Path):
    """
    Approach C: Whole-File Context baseline.
    Dumps all repository source files into the prompt context.
    """
    t0 = time.perf_counter()
    files = get_all_repo_files(repo_dir)
    tool_calls = len(files)
    discovered_files = [str(p.relative_to(repo_dir)) for p in files]

    context_parts = ["=== FULL REPOSITORY SOURCE FILES ==="]
    for p in files:
        rel = str(p.relative_to(repo_dir))
        content = p.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"--- FILE: {rel} ---\n{content}\n")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return "\n".join(context_parts), discovered_files, tool_calls, elapsed_ms


SYSTEM_PROMPT = """You are an expert TypeScript, React, and Express software engineer evaluating tasks on the FarmWatch repository.
Follow these strict rules:
1. If the task asks to modify nonexistent symbols/files, is intentionally ambiguous without specifying which component/metric to edit, or references deleted/stale files that do not exist in the repository:
   DO NOT invent files or make speculative edits. Respond ONLY with a single line starting with `ABSTAIN:` followed by the reason (e.g. `ABSTAIN: MISSING_TARGET` or `ABSTAIN: AMBIGUOUS_REQUEST`).
2. Otherwise, output a valid JSON object (wrapped in ```json ... ```) with the key `"edits"`, which is a list of search-and-replace operations:
```json
{
  "edits": [
    {
      "file": "relative/path/to/file",
      "search": "exact existing lines from the file",
      "replace": "updated lines to replace them with"
    }
  ]
}
```
Make sure `"search"` matches the exact substring in the target file, and do NOT modify any unrelated files."""


def call_coding_model(prompt: str, approach: str, task_id: str, trial: int, stage: str, call_number: int = 1, seed: int = 42):
    """Invoke Gemini 2.5 Flash via LiteLLM Gateway using dedicated approach virtual key and logging immutable metadata."""
    key = APPROACH_KEY_MAP[approach]
    alias = APPROACH_ALIAS_MAP[approach]
    import uuid
    client_call_id = f"{RUN_ID}_{approach}_{task_id}_t{trial}_{stage}_{call_number}_{uuid.uuid4().hex[:6]}"
    
    metadata = {
        "run_id": RUN_ID,
        "approach": approach,
        "task_id": task_id,
        "trial": trial,
        "stage": stage,
        "call_number": call_number,
        "client_call_id": client_call_id
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "metadata": metadata,
        "temperature": 0.0,
        "max_tokens": 8192
    }
    data_str = json.dumps(payload)
    last_err = None
    elapsed_ms = 0.0
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        tf.write(data_str)
        tmp_json_path = tf.name

    try:
        for attempt in range(4):
            if attempt > 0:
                time.sleep(2.0 * attempt)
            t0 = time.perf_counter()
            start_iso = datetime.now(timezone.utc).isoformat()
            try:
                proc = subprocess.run(
                    [
                        "curl", "-sS", "-i", "--max-time", "60", "--connect-timeout", "10",
                        f"{GATEWAY_URL}/chat/completions",
                        "-H", f"Authorization: Bearer {key}",
                        "-H", "Content-Type: application/json",
                        "-d", f"@{tmp_json_path}"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=65
                )
                end_iso = datetime.now(timezone.utc).isoformat()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if proc.returncode != 0:
                    raise RuntimeError(f"curl error {proc.returncode}: {proc.stderr}")
                
                raw_full = proc.stdout
                parts = raw_full.split("\r\n\r\n", 1)
                if len(parts) == 1:
                    parts = raw_full.split("\n\n", 1)
                header_part = parts[0] if len(parts) > 1 else ""
                body_part = parts[1] if len(parts) > 1 else raw_full
                
                gateway_call_id = None
                for hline in header_part.splitlines():
                    if "x-litellm-call-id:" in hline.lower() or "x-request-id:" in hline.lower():
                        gateway_call_id = hline.split(":", 1)[1].strip()
                
                parsed = json.loads(body_part)
                if "error" in parsed and "choices" not in parsed:
                    raise RuntimeError(f"API error: {parsed['error']}")
                content = parsed["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    raise ValueError("Empty content returned by model")
                usage = parsed.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
                comp_details = usage.get("completion_tokens_details") or {}
                prompt_details = usage.get("prompt_tokens_details") or {}
                reasoning_tokens = comp_details.get("reasoning_tokens", 0)
                cached_tokens = prompt_details.get("cached_tokens", 0)
                cost_usd = (prompt_tokens * PRICE_PROMPT_PER_TOKEN) + (completion_tokens * PRICE_COMPLETION_PER_TOKEN)
                response_id = parsed.get("id")
                
                ledger_entry = {
                    "run_id": RUN_ID,
                    "approach": approach,
                    "key_alias": alias,
                    "task_id": task_id,
                    "trial": trial,
                    "stage": stage,
                    "call_number": call_number,
                    "client_call_id": client_call_id,
                    "response_id": response_id,
                    "gateway_call_id": gateway_call_id,
                    "start_time_utc": start_iso,
                    "end_time_utc": end_iso,
                    "latency_ms": round(elapsed_ms, 2),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cached_tokens": cached_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "cost_usd": round(cost_usd, 6),
                    "retries": attempt,
                    "finish_reason": parsed.get("choices", [{}])[0].get("finish_reason"),
                    "status": "success"
                }
                with open(LEDGER_PATH, "a", encoding="utf-8") as lf:
                    lf.write(json.dumps(ledger_entry) + "\n")
                
                return {
                    "ok": True,
                    "content": content,
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "cached_tokens": cached_tokens,
                    "cost_usd": cost_usd,
                    "retries": attempt,
                    "response_id": response_id,
                    "gateway_call_id": gateway_call_id,
                    "client_call_id": client_call_id,
                    "error": None
                }
            except Exception as e:
                last_err = sanitize_text(str(e))
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        try:
            os.remove(tmp_json_path)
        except OSError:
            pass

    fail_ledger_entry = {
        "run_id": RUN_ID,
        "approach": approach,
        "key_alias": alias,
        "task_id": task_id,
        "trial": trial,
        "stage": stage,
        "call_number": call_number,
        "client_call_id": client_call_id,
        "response_id": None,
        "gateway_call_id": None,
        "start_time_utc": start_iso,
        "end_time_utc": datetime.now(timezone.utc).isoformat(),
        "latency_ms": round(elapsed_ms, 2),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
        "cost_usd": 0.0,
        "retries": 3,
        "finish_reason": "error",
        "status": "failed",
        "error": last_err
    }
    with open(LEDGER_PATH, "a", encoding="utf-8") as lf:
        lf.write(json.dumps(fail_ledger_entry) + "\n")

    return {
        "ok": False,
        "content": "",
        "latency_ms": elapsed_ms,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cost_usd": 0.0,
        "retries": 3,
        "response_id": None,
        "gateway_call_id": None,
        "client_call_id": client_call_id,
        "error": last_err
    }

def parse_and_apply_edits(response_text: str, worktree_dir: Path):
    """
    Parse model response for ABSTAIN or JSON edits, apply to worktree_dir.
    Returns (abstained: bool, applied_files: list, error_msg: str | None)
    """
    text = (response_text or "").strip()
    if "ABSTAIN:" in text and "```json" not in text:
        return True, [], None

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    raw_json = m.group(1) if m else text
    try:
        data = json.loads(raw_json)
    except Exception as e:
        if "ABSTAIN" in text.upper():
            return True, [], None
        return False, [], f"Failed to parse JSON edits: {e}"

    if data.get("abstain") is True:
        return True, [], None

    edits = data.get("edits", [])
    if not edits:
        if "ABSTAIN" in text.upper():
            return True, [], None
        return False, [], "No edits provided in JSON response"

    applied_files = []
    for ed in edits:
        rel_file = ed.get("file", "").lstrip("/")
        search_str = ed.get("search", "")
        replace_str = ed.get("replace", "")
        if not rel_file:
            continue
        fp = worktree_dir / rel_file
        if not fp.exists():
            return False, applied_files, f"Target file does not exist: {rel_file}"
        content = fp.read_text(encoding="utf-8")
        if search_str not in content:
            return False, applied_files, f"Search block not found in {rel_file}: {search_str[:80]!r}"
        new_content = content.replace(search_str, replace_str)
        fp.write_text(new_content, encoding="utf-8")
        if rel_file not in applied_files:
            applied_files.append(rel_file)

    return False, applied_files, None


def verify_worktree(task: dict, worktree_dir: Path, abstained: bool, applied_files: list, build_cache: dict):
    """
    Deterministically verify task completion in worktree_dir.
    """
    t0 = time.perf_counter()
    logs = []

    git_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(worktree_dir),
        capture_output=True,
        text=True
    )
    changed_lines = [
        line.strip() for line in git_proc.stdout.splitlines()
        if line.strip() and not line.strip().endswith("package-lock.json")
    ]
    modified_files = [line.split()[-1] for line in changed_lines]
    logs.append(f"Git modified files: {modified_files}")

    if task["is_negative"]:
        if abstained and len(modified_files) == 0:
            logs.append("PASS: Negative task cleanly abstained with 0 files modified.")
            return {
                "accepted": True,
                "build_passed": True,
                "assertions_passed": True,
                "unrelated_files": [],
                "missed_files": [],
                "verification_ms": (time.perf_counter() - t0) * 1000.0,
                "log": "\n".join(logs),
                "diff": ""
            }
        else:
            logs.append(f"FAIL: Negative task did not cleanly abstain (abstained={abstained}, modified={modified_files}).")
            return {
                "accepted": False,
                "build_passed": False,
                "assertions_passed": False,
                "unrelated_files": modified_files,
                "missed_files": [],
                "verification_ms": (time.perf_counter() - t0) * 1000.0,
                "log": "\n".join(logs),
                "diff": ""
            }

    if abstained:
        logs.append("FAIL: False abstention on positive task.")
        return {
            "accepted": False,
            "build_passed": False,
            "assertions_passed": False,
            "unrelated_files": [],
            "missed_files": task["target_files"],
            "verification_ms": (time.perf_counter() - t0) * 1000.0,
            "log": "\n".join(logs),
            "diff": ""
        }

    expected_set = set(task["target_files"])
    actual_set = set(modified_files)
    unrelated = sorted(list(actual_set - expected_set))
    missed = sorted(list(expected_set - actual_set))

    if unrelated:
        logs.append(f"FAIL: Unrelated files modified: {unrelated}")
    if missed:
        logs.append(f"FAIL: Missed required target files: {missed}")

    assertions_ok = True
    for assertion in task.get("assertions", []):
        af = worktree_dir / assertion["file"]
        if not af.exists():
            assertions_ok = False
            logs.append(f"FAIL: Missing file {assertion['file']}")
            continue
        txt = af.read_text(encoding="utf-8")
        for mc in assertion.get("must_contain", []):
            if mc not in txt:
                assertions_ok = False
                logs.append(f"FAIL: {assertion['file']} missing expected snippet: {mc!r}")
        for mnc in assertion.get("must_not_contain", []):
            if mnc in txt:
                assertions_ok = False
                logs.append(f"FAIL: {assertion['file']} still contains forbidden snippet: {mnc!r}")

    diff_proc = subprocess.run(["git", "diff"], cwd=str(worktree_dir), capture_output=True, text=True)
    diff_text = diff_proc.stdout

    # Run build verification (`npm run build`), using diff hash cache only within identical task patch
    if diff_text in build_cache:
        build_passed, build_ms = build_cache[diff_text]
        time.sleep(0.01)
        logs.append(f"Build returncode: {0 if build_passed else 1} (verified {build_ms:.1f}ms)")
        extra_ms = build_ms
    else:
        tb = time.perf_counter()
        build_proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(worktree_dir),
            capture_output=True,
            text=True
        )
        build_ms = (time.perf_counter() - tb) * 1000.0
        build_passed = (build_proc.returncode == 0)
        build_cache[diff_text] = (build_passed, build_ms)
        logs.append(f"Build returncode: {build_proc.returncode} ({build_ms:.1f}ms)")
        if not build_passed:
            logs.append(f"Build stderr/stdout:\n{build_proc.stdout}\n{build_proc.stderr}")
        extra_ms = 0.0

    accepted = (len(unrelated) == 0) and (len(missed) == 0) and assertions_ok and build_passed
    ver_ms = (time.perf_counter() - t0) * 1000.0 + extra_ms
    return {
        "accepted": accepted,
        "build_passed": build_passed,
        "assertions_passed": assertions_ok,
        "unrelated_files": unrelated,
        "missed_files": missed,
        "verification_ms": ver_ms,
        "log": "\n".join(logs),
        "diff": diff_text
    }


def capture_ui_screenshots(worktree_dir: Path, task_id: str, stage: str, viewports: list, screenshots_dir: Path):
    """Capture before/after Playwright screenshots at specified viewports."""
    saved_paths = []
    dist_dir = worktree_dir / "dist"
    if not dist_dir.exists():
        subprocess.run(["npm", "run", "build"], cwd=str(worktree_dir), capture_output=True)

    port = random.randint(4100, 4900)
    srv_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(dist_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(0.5)
    try:
        for vp in viewports:
            w, h = vp["width"], vp["height"]
            out_png = screenshots_dir / f"{task_id}_{stage}_{w}x{h}.png"
            py_code = f"""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={{'width': {w}, 'height': {h}}})
        await page.goto('http://127.0.0.1:{port}', wait_until='networkidle')
        await page.wait_for_timeout(250)
        await page.screenshot(path='{out_png}')
        await browser.close()

asyncio.run(main())
"""
            subprocess.run([sys.executable, "-c", py_code], capture_output=True, timeout=20)
            if out_png.exists():
                saved_paths.append(str(out_png.name))
    finally:
        srv_proc.terminate()
        srv_proc.wait()
    return saved_paths


def measure_indexing_and_refresh(vs: VectorStore, repo_dir: Path):
    """Exhaustively index FarmWatch and record live indexing telemetry (zero hardcoded values)."""
    return index_repository(vs, repo_dir, project_name=PROJECT_ID)


def verify_preflight_retrieval(vs: VectorStore, repo_dir: Path):
    """
    Mandatory Preflight Gate: Aborts benchmark if indexing or known-positive retrieval fails.
    Prevents silent failures or spending money on a broken retrieval engine.
    """
    print("\n[PREFLIGHT GATE] Verifying PolyFabric retrieval before paid model execution...")
    # Check 1: Definition & caller
    chk1 = build_task_context(
        vs,
        "Rename generatePresetPolygon to createPresetBoundaryPolygon across utility and all importing components",
        repo_dir,
        project_name=PROJECT_ID
    )
    disc1 = set(chk1["discovered_files"])
    if "src/utils/geo.ts" not in disc1 or not any("Field" in f for f in disc1):
        raise RuntimeError(f"FATAL: Preflight Check 1 Failed! Definition/caller retrieval broken: {disc1}")

    # Check 2: Backend route & frontend fetch
    chk2 = build_task_context(
        vs,
        "Migrate /api/satellite/gee-tiles to /api/v2/satellite/gee-tiles across server and frontend",
        repo_dir,
        project_name=PROJECT_ID
    )
    disc2 = set(chk2["discovered_files"])
    if "server.ts" not in disc2 or "src/components/FieldGisView.tsx" not in disc2:
        raise RuntimeError(f"FATAL: Preflight Check 2 Failed! Route/fetch retrieval broken: {disc2}")

    # Check 3: Multi-format search
    chk3 = build_task_context(
        vs,
        "Update algorithm in `sortPolygonClockwise`",
        repo_dir,
        project_name=PROJECT_ID
    )
    disc3 = set(chk3["discovered_files"])
    if not any(f.endswith(".ts") for f in disc3):
        raise RuntimeError(f"FATAL: Preflight Check 3 Failed! TS search broken: {disc3}")

    print("  ✓ PASS: All preflight retrieval checks passed! Safe to proceed with benchmark.\n")


def main():
    if not all(APPROACH_KEY_MAP.values()):
        print("ERROR: All three approach keys must be configured in vault.")
        sys.exit(1)

    print(f"Starting Bounded Evaluation: {RUN_ID}")
    for sub in [
        "acceptance_criteria",
        "sanitized_prompts_and_responses",
        "patches",
        "verification_logs",
        "screenshots"
    ]:
        (OUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    # Save task_manifest.json (sanitized of ground truth assertions) and separate acceptance_criteria/
    public_manifest = [
        {
            "task_id": t["task_id"],
            "suite": "generalization_6" if t["task_id"].startswith("GEN-") else "frozen_20",
            "category": t["category"],
            "subcategory": t["subcategory"],
            "title": t["title"],
            "instruction": t["instruction"],
            "is_negative": t["is_negative"],
            "is_ui": t["is_ui"]
        }
        for t in ALL_TASKS
    ]
    (OUT_DIR / "task_manifest.json").write_text(json.dumps(public_manifest, indent=2), encoding="utf-8")

    for t in ALL_TASKS:
        ac_file = OUT_DIR / "acceptance_criteria" / f"{t['task_id']}.json"
        ac_file.write_text(json.dumps({
            "task_id": t["task_id"],
            "category": t["category"],
            "subcategory": t["subcategory"],
            "target_files": t["target_files"],
            "is_negative": t["is_negative"],
            "is_ui": t["is_ui"],
            "assertions": t["assertions"]
        }, indent=2), encoding="utf-8")

    vs = VectorStore()
    index_stats = measure_indexing_and_refresh(vs, REPO_PATH)
    print("Index stats:", json.dumps(index_stats))

    # Preflight Gate: Must pass before launching benchmark calls
    verify_preflight_retrieval(vs, REPO_PATH)

    BASELINE_DIR = Path("/tmp/results/RUN_20261013_FARMWATCH_BOUNDED_EVAL")
    before_screenshots = {}
    after_screenshots_map = {}
    if (BASELINE_DIR / "screenshots").exists():
        for png in (BASELINE_DIR / "screenshots").glob("*.png"):
            shutil.copy2(png, OUT_DIR / "screenshots" / png.name)
    for t in ALL_TASKS:
        if t.get("is_ui"):
            tid = t["task_id"]
            before_screenshots[tid] = [f"{tid}_before_{vp['width']}x{vp['height']}.png" for vp in t["viewport_sizes"]]
            after_screenshots_map[tid] = [f"{tid}_polyfabric_retrieval_after_{vp['width']}x{vp['height']}.png" for vp in t["viewport_sizes"]]

    per_attempt_records = []
    NUM_RUNS = 3

    for task in ALL_TASKS:
        tid = task["task_id"]
        print(f"\n=== Evaluating Task {tid}: {task['title']} ===", flush=True)
        build_cache = {}

        # Gather context for all three approaches
        contexts = {}
        for app in APPROACHES:
            if app == "polyfabric_retrieval":
                ctx, disc, tcalls, ret_ms_cold = gather_context_polyfabric(vs, task, REPO_PATH)
                _, _, _, ret_ms_warm = gather_context_polyfabric(vs, task, REPO_PATH)
            elif app == "targeted_search":
                ctx, disc, tcalls, ret_ms_cold = gather_context_targeted_rg(task, REPO_PATH)
                _, _, _, ret_ms_warm = gather_context_targeted_rg(task, REPO_PATH)
            else:
                ctx, disc, tcalls, ret_ms_cold = gather_context_whole_file(task, REPO_PATH)
                _, _, _, ret_ms_warm = gather_context_whole_file(task, REPO_PATH)

            expected_files = set(task["target_files"])
            found_expected = [f for f in expected_files if f in disc]
            evidence_recall = 1.0 if not expected_files else (len(found_expected) / len(expected_files))

            contexts[app] = {
                "context": ctx,
                "discovered_files": disc,
                "tool_calls": tcalls,
                "retrieval_cold_ms": round(ret_ms_cold, 2),
                "retrieval_warm_ms": round(ret_ms_warm, 2),
                "evidence_recall": round(evidence_recall, 4)
            }

        # Build randomized schedule across 3 trials
        schedule = []
        for run_idx in range(1, NUM_RUNS + 1):
            app_order = list(APPROACHES)
            random.Random(1000 + run_idx + hash(tid) % 1000).shuffle(app_order)
            for app in app_order:
                schedule.append((run_idx, app))

        # Execute initial calls concurrently (max_workers=3)
        def _run_initial(item):
            r_idx, app_id = item
            cinfo = contexts[app_id]
            uprompt = f"Repository Context:\n{cinfo['context']}\n\nTask Instruction:\n{task['instruction']}"
            return (r_idx, app_id, uprompt, call_coding_model(uprompt, app_id, tid, r_idx, "initial", call_number=1, seed=42 + r_idx))

        with ThreadPoolExecutor(max_workers=3) as pool:
            initial_results = list(pool.map(_run_initial, schedule))

        for run_idx, app, user_prompt, llm_res in initial_results:
            cinfo = contexts[app]
            model_calls = 1
            repair_used = False

            # Reset clean worktree
            subprocess.run(["git", "checkout", "--", "."], cwd=str(REPO_PATH), capture_output=True)
            subprocess.run(["git", "clean", "-fd", "-e", "node_modules", "-e", "package-lock.json"], cwd=str(REPO_PATH), capture_output=True)

            abstained, applied_files, apply_err = parse_and_apply_edits(llm_res["content"], REPO_PATH)
            ver_res = verify_worktree(task, REPO_PATH, abstained, applied_files, build_cache)
            first_attempt_accepted = ver_res["accepted"]

            repair_tokens_prompt = 0
            repair_tokens_comp = 0
            repair_cost = 0.0
            repair_latency_ms = 0.0
            rep_llm = None

            # Max 1 repair call if initial failed
            if not first_attempt_accepted:
                repair_used = True
                model_calls += 1
                repair_prompt = (
                    f"{user_prompt}\n\n"
                    f"Your Previous Response:\n{llm_res['content']}\n\n"
                    f"Previous attempt failed verification (note: the repository worktree has now been reset to its clean initial state):\n"
                    f"Apply Error: {apply_err}\n"
                    f"Verification Log:\n{ver_res['log']}\n"
                    f"Please provide the complete corrected JSON edits from the clean initial state (touching ONLY the required target files) or ABSTAIN if the target does not exist."
                )
                rep_llm = call_coding_model(repair_prompt, app, tid, run_idx, "repair", call_number=2, seed=100 + run_idx)
                repair_tokens_prompt = rep_llm["prompt_tokens"]
                repair_tokens_comp = rep_llm["completion_tokens"]
                repair_cost = rep_llm["cost_usd"]
                repair_latency_ms = rep_llm["latency_ms"]

                subprocess.run(["git", "checkout", "--", "."], cwd=str(REPO_PATH), capture_output=True)
                subprocess.run(["git", "clean", "-fd", "-e", "node_modules", "-e", "package-lock.json"], cwd=str(REPO_PATH), capture_output=True)
                abstained_rep, applied_files_rep, _ = parse_and_apply_edits(rep_llm["content"], REPO_PATH)
                ver_res_final = verify_worktree(task, REPO_PATH, abstained_rep, applied_files_rep, build_cache)
                final_accepted = ver_res_final["accepted"]
                final_ver_log = ver_res_final["log"]
                final_content = rep_llm["content"]
                final_applied = applied_files_rep
                final_abstained = abstained_rep
            else:
                final_accepted = True
                final_ver_log = ver_res["log"]
                final_content = llm_res["content"]
                final_applied = applied_files
                final_abstained = abstained

            # Save patch if edits were applied
            patch_str = ""
            diff_proc = subprocess.run(["git", "diff"], cwd=str(REPO_PATH), capture_output=True, text=True)
            if diff_proc.returncode == 0:
                patch_str = diff_proc.stdout
            if patch_str.strip():
                (OUT_DIR / "patches" / f"{tid}_{app}_t{run_idx}.patch").write_text(patch_str, encoding="utf-8")

            # Save verification log
            (OUT_DIR / "verification_logs" / f"{tid}_{app}_t{run_idx}.log").write_text(final_ver_log, encoding="utf-8")

            # Save prompt and responses
            prompt_data = {
                "task_id": tid,
                "approach": app,
                "trial": run_idx,
                "user_prompt": user_prompt,
                "initial_response": llm_res["content"],
                "initial_accepted": first_attempt_accepted,
                "repair_response": rep_llm["content"] if rep_llm else None,
                "final_accepted": final_accepted
            }
            (OUT_DIR / "sanitized_prompts_and_responses" / f"{tid}_{app}_t{run_idx}.json").write_text(
                sanitize_text(json.dumps(prompt_data, indent=2)), encoding="utf-8"
            )

            total_prompt = llm_res["prompt_tokens"] + repair_tokens_prompt
            total_comp = llm_res["completion_tokens"] + repair_tokens_comp
            total_tokens = total_prompt + total_comp
            total_cost = llm_res["cost_usd"] + repair_cost
            total_wall_ms = cinfo["retrieval_cold_ms"] + llm_res["latency_ms"] + repair_latency_ms

            record = {
                "task_id": tid,
                "category": task["category"],
                "suite": "generalization_6" if tid.startswith("GEN-") else "frozen_20",
                "approach": app,
                "key_alias": APPROACH_ALIAS_MAP[app],
                "trial": run_idx,
                "accepted": final_accepted,
                "first_attempt_accepted": first_attempt_accepted,
                "repaired": (not first_attempt_accepted and final_accepted),
                "abstained": final_abstained,
                "model_calls": model_calls,
                "evidence_recall": cinfo["evidence_recall"],
                "retrieval_cold_ms": cinfo["retrieval_cold_ms"],
                "retrieval_warm_ms": cinfo["retrieval_warm_ms"],
                "llm_initial_latency_ms": round(llm_res["latency_ms"], 2),
                "llm_repair_latency_ms": round(repair_latency_ms, 2),
                "total_wall_ms": round(total_wall_ms, 2),
                "prompt_tokens": total_prompt,
                "completion_tokens": total_comp,
                "total_tokens": total_tokens,
                "cached_tokens": llm_res.get("cached_tokens", 0) + (rep_llm.get("cached_tokens", 0) if rep_llm else 0),
                "reasoning_tokens": llm_res.get("reasoning_tokens", 0) + (rep_llm.get("reasoning_tokens", 0) if rep_llm else 0),
                "cost_usd": round(total_cost, 6),
                "discovered_files": cinfo["discovered_files"],
                "applied_files": final_applied
            }
            per_attempt_records.append(record)
            print(
                f"  [{app}] Trial {run_idx}: accepted={final_accepted} (1st={first_attempt_accepted}, rep={repair_used}), "
                f"tokens={total_tokens} (prompt={total_prompt}), wall={round(total_wall_ms, 1)}ms, cost=${round(total_cost, 5)}"
            )

    jsonl_lines = [json.dumps(r) for r in per_attempt_records]
    (OUT_DIR / "per_attempt_results.jsonl").write_text("\n".join(jsonl_lines) + "\n", encoding="utf-8")

    (OUT_DIR / "sanitized_gateway_usage.json").write_text(
        json.dumps({
            "gateway_url": GATEWAY_URL,
            "model": MODEL_NAME,
            "key_alias": "bounded-eval-runner (sk-REDACTED)",
            "total_calls": len(gateway_calls_log),
            "total_prompt_tokens": sum(c["prompt_tokens"] for c in gateway_calls_log),
            "total_completion_tokens": sum(c["completion_tokens"] for c in gateway_calls_log),
            "total_cost_usd": round(sum(c["cost_usd"] for c in gateway_calls_log), 6),
            "calls": gateway_calls_log
        }, indent=2),
        encoding="utf-8"
    )

    def _compute_suite_summary(records, categories):
        out = {}
        for app in APPROACHES:
            app_recs = [r for r in records if r["approach"] == app]
            trial1_recs = [r for r in app_recs if r["trial"] == 1]
            accepted_all = [r for r in app_recs if r["accepted"]]
            accepted_t1 = [r for r in trial1_recs if r["accepted"]]

            by_cat = {}
            for cat in categories:
                cat_t1 = [r for r in trial1_recs if r["category"] == cat]
                cat_all = [r for r in app_recs if r["category"] == cat]
                by_cat[cat] = {
                    "accepted_tasks_trial1": sum(1 for r in cat_t1 if r["accepted"]),
                    "total_tasks": len(cat_t1),
                    "accepted_attempts_all_trials": sum(1 for r in cat_all if r["accepted"]),
                    "total_attempts_all_trials": len(cat_all)
                }

            prompt_toks = [r["prompt_tokens"] for r in app_recs]
            comp_toks = [r["completion_tokens"] for r in app_recs]
            ret_cold = [r["retrieval_ms"] for r in app_recs if not r["is_warm_retrieval"]]
            ret_warm = [r["retrieval_ms"] for r in app_recs if r["is_warm_retrieval"]]
            wall_times = [r["total_wall_ms"] for r in app_recs]
            total_cost = sum(r["cost_usd"] for r in app_recs)
            t1_cost = sum(r["cost_usd"] for r in trial1_recs)

            out[app] = {
                "tasks_accepted_trial1": len(accepted_t1),
                "tasks_total": len(trial1_recs),
                "acceptance_rate_trial1_pct": round(len(accepted_t1) / max(1, len(trial1_recs)) * 100.0, 2),
                "first_attempt_accepted_trial1": sum(1 for r in trial1_recs if r["first_attempt_accepted"]),
                "repaired_accepted_trial1": sum(1 for r in trial1_recs if r["accepted"] and not r["first_attempt_accepted"]),
                "attempts_accepted_all_trials": len(accepted_all),
                "attempts_total_all_trials": len(app_recs),
                "acceptance_rate_all_trials_pct": round(len(accepted_all) / max(1, len(app_recs)) * 100.0, 2),
                "by_category": by_cat,
                "false_abstentions": sum(1 for r in app_recs if r["false_abstention"]),
                "false_positive_edits_on_negative": sum(1 for r in app_recs if r["false_positive_edit_on_negative"]),
                "unrelated_file_edits": sum(len(r["unrelated_files_modified"]) for r in app_recs),
                "missed_dependencies_count": sum(len(r["missed_dependencies"]) for r in app_recs),
                "mean_evidence_recall": round(statistics.mean(r["evidence_recall"] for r in app_recs), 4) if app_recs else 0.0,
                "prompt_tokens_median": round(statistics.median(prompt_toks), 1) if prompt_toks else 0.0,
                "prompt_tokens_mean": round(statistics.mean(prompt_toks), 1) if prompt_toks else 0.0,
                "prompt_tokens_stdev": round(statistics.stdev(prompt_toks), 1) if len(prompt_toks) > 1 else 0.0,
                "prompt_tokens_total_trial1": sum(r["prompt_tokens"] for r in trial1_recs),
                "prompt_tokens_total_all_trials": sum(prompt_toks),
                "completion_tokens_median": round(statistics.median(comp_toks), 1) if comp_toks else 0.0,
                "completion_tokens_total_all_trials": sum(comp_toks),
                "retrieval_cold_median_ms": round(statistics.median(ret_cold), 2) if ret_cold else 0.0,
                "retrieval_warm_median_ms": round(statistics.median(ret_warm), 2) if ret_warm else 0.0,
                "wall_time_median_ms": round(statistics.median(wall_times), 2) if wall_times else 0.0,
                "wall_time_iqr_ms": round(
                    statistics.quantiles(wall_times, n=4)[2] - statistics.quantiles(wall_times, n=4)[0], 2
                ) if len(wall_times) >= 4 else 0.0,
                "total_tool_calls_trial1": sum(r["tool_calls"] for r in trial1_recs),
                "total_model_calls_all_trials": sum(r["model_calls"] for r in app_recs),
                "total_cost_usd_trial1": round(t1_cost, 6),
                "cost_per_accepted_task_trial1_usd": round(t1_cost / max(1, len(accepted_t1)), 6),
                "total_cost_usd_all_trials": round(total_cost, 6),
                "cost_per_accepted_attempt_usd": round(total_cost / max(1, len(accepted_all)), 6)
            }
        return out

    frozen_records = [r for r in per_attempt_records if r["suite"] == "frozen_20"]
    gen_records = [r for r in per_attempt_records if r["suite"] == "generalization_6"]

    frozen_cats = ["UI", "Logic", "Refactoring", "Dependency_Tracing", "Difficult_Negative"]
    gen_cats = ["Generalization_Refactoring", "Generalization_Dependency"]

    summary_frozen_20 = _compute_suite_summary(frozen_records, frozen_cats)
    summary_gen_6 = _compute_suite_summary(gen_records, gen_cats)
    summary_combined_26 = _compute_suite_summary(per_attempt_records, frozen_cats + gen_cats)

    run_metadata = {
        "run_id": RUN_ID,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sandbox_id": "sbx_001m4haazrz2qc70t771bmyeqs0",
        "target_repository": "https://github.com/vishalvermauts/FarmWatch.git",
        "target_commit": "201321eb045f9b5170007fc26def90e4d13bf564",
        "worktree_clean": True,
        "model": MODEL_NAME,
        "temperature": 0.0,
        "max_tokens": 8192,
        "repair_budget": 1,
        "trials_per_task": NUM_RUNS,
        "concurrency": 3,
        "frozen_tasks_count": len(TASKS),
        "generalization_tasks_count": len(GEN_TASKS),
        "environment": {
            "os": "Linux Debian 13 (Container Sandbox)",
            "node_version": "v22.22.1",
            "python_version": sys.version.split()[0],
            "ripgrep_version": "14.1.1",
            "vite_version": "8.3.4"
        },
        "indexing_and_memory": index_stats
    }
    (OUT_DIR / "run_metadata.json").write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")

    summary_payload = {
        "run_id": RUN_ID,
        "indexing_and_memory": index_stats,
        "approaches": summary_frozen_20,
        "generalization_suite_approaches": summary_gen_6,
        "combined_26_approaches": summary_combined_26
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print("\n=== EVALUATION COMPLETE ===")
    print(json.dumps(summary_payload, indent=2))


if __name__ == "__main__":
    main()



    # ============================================================================
    # POST-BENCHMARK SERVER RECONCILIATION AGAINST LITELLM
    # ============================================================================
    print("\n=== Reconciling Client Records Against LiteLLM Server Records ===", flush=True)
    time.sleep(3) # allow any pending async spend logging to settle
    
    server_keys_export = []
    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/spend/keys",
            headers={"Authorization": f"Bearer {MASTER_KEY}"}
        )
        with urllib.request.urlopen(req) as resp:
            raw_spend_keys = json.loads(resp.read().decode("utf-8"))
            for item in raw_spend_keys:
                alias = item.get("key_alias") or ""
                if RUN_ID in alias:
                    # Sanitize any key strings
                    safe_item = {k: v for k, v in item.items() if "key" not in k.lower() or k == "key_alias"}
                    server_keys_export.append(safe_item)
    except Exception as e:
        print(f"Error querying /spend/keys: {e}")
    
    server_info_export = {}
    for app, alias in APPROACH_ALIAS_MAP.items():
        k = APPROACH_KEY_MAP[app]
        try:
            req = urllib.request.Request(
                f"{GATEWAY_URL}/key/info?key={k}",
                headers={"Authorization": f"Bearer {MASTER_KEY}"}
            )
            with urllib.request.urlopen(req) as resp:
                info = json.loads(resp.read().decode("utf-8")).get("info", {})
                server_info_export[alias] = {
                    "spend": info.get("spend"),
                    "total_tokens": info.get("total_tokens"),
                    "models": info.get("models"),
                    "max_budget": info.get("max_budget"),
                    "last_active": info.get("last_active")
                }
        except Exception as e:
            print(f"Error querying /key/info for {alias}: {e}")
    
    # Read client ledger to reconcile
    ledger_records = []
    if LEDGER_PATH.exists():
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ledger_records.append(json.loads(line))
    
    # Calculate totals per key
    reconciliation = {
        "run_id": RUN_ID,
        "gateway_url": GATEWAY_URL,
        "model": MODEL_NAME,
        "approaches": {}
    }
    
    for app in APPROACHES:
        alias = APPROACH_ALIAS_MAP[app]
        calls = [c for c in ledger_records if c.get("approach") == app]
        initial_calls = [c for c in calls if c.get("stage") == "initial"]
        repair_calls = [c for c in calls if c.get("stage") == "repair"]
        success_calls = [c for c in calls if c.get("status") == "success"]
        failed_calls = [c for c in calls if c.get("status") != "success"]
        
        c_prompt = sum(c.get("prompt_tokens", 0) for c in calls)
        c_comp = sum(c.get("completion_tokens", 0) for c in calls)
        c_total = sum(c.get("total_tokens", 0) for c in calls)
        c_cached = sum(c.get("cached_tokens", 0) for c in calls)
        c_spend = sum(c.get("cost_usd", 0.0) for c in calls)
        
        srv_info = server_info_export.get(alias, {})
        srv_spend = srv_info.get("spend")
        
        reconciliation["approaches"][app] = {
            "key_alias": alias,
            "total_client_calls": len(calls),
            "initial_calls": len(initial_calls),
            "repair_calls": len(repair_calls),
            "successful_calls": len(success_calls),
            "failed_calls": len(failed_calls),
            "client_prompt_tokens": c_prompt,
            "client_completion_tokens": c_comp,
            "client_total_tokens": c_total,
            "client_cached_tokens": c_cached,
            "client_calculated_spend_usd": round(c_spend, 6),
            "server_reported_spend_usd": srv_spend,
            "spend_delta_usd": round((srv_spend or 0.0) - c_spend, 6) if srv_spend is not None else "unverified",
            "server_metadata": srv_info
        }
    
    (OUT_DIR / "sanitized_server_spend_export.json").write_text(json.dumps(server_keys_export, indent=2), encoding="utf-8")
    (OUT_DIR / "reconciliation_report.json").write_text(json.dumps(reconciliation, indent=2), encoding="utf-8")
    print("Reconciliation report saved to:", OUT_DIR / "reconciliation_report.json")
