# CircuitCycle

CircuitCycle classifies laptop components from a photo and provides component-specific
reuse, recycling, handling, and safety guidance. It serves the existing HTML frontend
from Flask.

## Dataset inspection

The supplied dataset is under
`dataset/Laptop Components Image Dataset to Classify Different Components/`.
Its category folders are nested one level deeper than the PDF describes:

- `Raw Data/Raw Data/<number>. <Component>/`
- `Augmented Data/Augmented Data/<number>. <Component>/`

The inspected dataset has 26 balanced categories: Battery, DVDRom, Hinge, Keyboard,
Motherboard, DCCable, PowerSwitch, RAM, ScrewKit, USBPort, WifiCard, Speaker,
CMOSBattery, HardDiskDrive, WebCam, LCDScreen, Bezel, HeatSink, SSD, CPUFan,
TouchPad, Processor, RAMCover, BasePanel, TopPanel, and LVDSCable. Each class has
140 raw and 980 augmented JPGs (3,640 raw and 25,480 augmented; 29,120 total).
All 29,120 images were verified as readable JPEGs at 900 x 1200 pixels. SHA-256
checks found no exact duplicates within either split. Near-duplicate image hashes
are only candidate indicators: a raw-image pHash screen found 3,180 within-class
pairs at Hamming distance <= 4, but visual spot checks included distinct views
with matching hashes because the images share a plain background. Those are
review candidates, not 3,180 confirmed duplicates, and are not automatically
removed or grouped. Files with matching raw/augmented basenames were not reliable
source links in visual spot checks.

The PDF says 1200 x 900 pixels and describes the two data directories as directly
containing class folders; both details differ from the inspected files. It does not
document augmentation methods or source-image IDs. For that reason, the existing
augmented images are preserved but excluded from training and validation. Training
augmentation is generated online from training images only.

Run the full inventory and exact-duplicate report:

```powershell
py -m backend.inspect_dataset
```

The report is written under `backend/artifacts/` and does not modify source images.

## Environment and model training

Use Python 3.12. TensorFlow and the other dependencies are listed in
`requirements.txt`.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:FLASK_SECRET_KEY = py -c "import secrets; print(secrets.token_hex(32))"
```

The current native-Windows TensorFlow environment exposes CPU only, not the
installed NVIDIA RTX 4050. Benchmark both architectures before a long training run:

```powershell
py -m backend.train_model --benchmark --architecture compare
```

The benchmark uses a few synthetic batches and estimates model-only epoch time; it
also reports model-only inference throughput. It does not measure image loading,
validation, or actual accuracy. It downloads
ImageNet weights from the Keras model-weight source if they are not cached. If the
CPU benchmark is too slow, run the same commands in a compatible WSL2/Linux CUDA
environment.

Training splits only raw images, with 112 train and 28 validation images per class
at the default 80/20 ratio. Exact duplicate files are kept in the same split.
No independent test data is read during training or tuning.

```powershell
py -m backend.train_model --architecture compare
```

MobileNetV2 and EfficientNetB0 use ImageNet weights, train-only augmentation,
frozen-backbone head training, lower-rate fine-tuning, early stopping, and
validation-based checkpointing. The architecture with the higher validation macro
F1 is copied to `backend/artifacts/best_ewaste_model.keras`. Training also writes
`class_indices.json` with the exact output-index mapping used by Flask and a
deterministic raw-image 80/20 split manifest. The same directory contains training/
validation metrics, per-class reports, confusion matrices, and the fixed 0.50
confidence-rejection threshold. Validation metrics are
not independent test metrics. The fixed threshold is an operational cutoff and
does not validate rejection of unrelated images.

To keep tuning separate from any future independent test, do not add that dataset
to the training command. When supplied, place it under
`dataset/independent_test/<Component>/` and evaluate the finalized model once:

```powershell
py -m backend.evaluate_independent
```

The independent evaluation refuses to run if the directory is absent, labels do
not map to model classes, images are invalid, or exact content overlaps the
training/validation manifest. Independent-test metrics remain pending until this
dataset has actually been added and evaluated.

## Run the application

On Windows, run the project with:

```powershell
.\run-project.ps1
```

The script creates the Python 3.12 environment if needed, installs missing
dependencies, keeps a local Flask secret, and starts the server.

Set `FLASK_SECRET_KEY` to a persistent random secret before running the server.
`FLASK_DEBUG=1` is available only for local development; debug is off by default.

```powershell
py -m backend.app
```

Open `http://localhost:5000`. The classify page accepts an uploaded or
camera-captured JPEG, PNG, or WebP up to 10 MB. The backend does not save
classification uploads. Until model training has produced all required artifacts,
`POST /api/classify` returns HTTP 503 rather than a placeholder prediction.

## Streamlit classifier

The standalone Streamlit interface reuses the saved classifier and supports both
image uploads and camera capture. Start it from the project root:

```powershell
python -m streamlit run backend\streamlit_app.py
```

The component recyclability and hazard lookup is defined in
`backend/component_info.py`. Unknown class names display `Unknown` for both
properties.

The classification endpoint is `POST /api/classify` with multipart field `image`
or a JSON `image` value containing a JPEG, PNG, or WebP base64 data URI.
The feedback endpoint is `POST /api/feedback` with JSON fields
`classification_correct`, `recommendation_useful`, `overall_rating` (1–5),
`comments` (optional, at most 1,000 characters), and `component` (optional).
Feedback is stored in `backend/data/feedback.sqlite3`.

## Account data notice

The tracked `users.json` contains account data and profile images; protect it as
private data. New registrations and password resets store PBKDF2 password hashes;
a successful login upgrades any legacy plaintext password in place. Configure
`FLASK_SECRET_KEY` outside the repository. Changing these files does not remove
any credentials already present in Git history.

## Email password recovery

The login page's **Forgot Password?** link opens the email recovery page. The
backend emails a single-use, random reset link that expires after 15 minutes.
Reset links can be re-requested after a 60-second cooldown. The new password is
stored as the same PBKDF2 hash used for registration. No database migration is
needed; token digests and expiry timestamps are held in the backend process.

For Gmail, enable 2-Step Verification on the sending Google account and create an
App Password. Do not use the account's normal Google password. Copy the example
environment file and enter the App Password and sender address:

```powershell
Copy-Item .env.example backend\.env
notepad backend\.env
```

Set `SMTP_USERNAME` and `SMTP_FROM` to the Gmail sender address, `SMTP_PASSWORD`
to the 16-character Google App Password (spaces are optional), and
`SMTP_SERVER=smtp.gmail.com` with `SMTP_PORT=587`. Set `APP_BASE_URL` to the
public origin used to open the app (keep `http://localhost:5000` for local
development). Set `FLASK_SECRET_KEY` to a long, random secret and keep
`backend\.env` private; it is ignored by Git. For example:

```powershell
py -c "import secrets; print(secrets.token_hex(32))"
```

Copy the printed value into `backend\.env` as `FLASK_SECRET_KEY`. Keep
`FLASK_COOKIE_SECURE=0` for local HTTP development; set it to `1` when serving the
site over HTTPS. The app loads `backend\.env` at startup. Install the added dependency
alongside the project requirements and start the backend:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run-project.ps1
```

Open `http://localhost:5000` and request a reset using an address registered in
`users.json`. Open the link delivered to that inbox to choose a new password.
Email delivery requires valid SMTP credentials and network access to Gmail.
Reset-token state is held in the running Flask process, so use one application
process for local development; a multi-worker deployment should use shared
server-side storage for reset state.

## Tests

Run the backend and dataset-pipeline tests with:

```powershell
py -m pytest
```
