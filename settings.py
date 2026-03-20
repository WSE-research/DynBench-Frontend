from decouple import config


DEFAULT_QUERY_INPUT_HEIGHT = 24  # pixels
MODEL = config('MODEL')
GITHUB_REPO = config(
    "GITHUB_REPO", "https://github.com/WSE-research/DynBench-Frontend.git"
)

DYNBENCH_URL = config('DYNBENCH')
TRANSFORM_URL = DYNBENCH_URL + '/transform'
FEEDBACK_URL = DYNBENCH_URL + '/feedback'
MODELS_URL = DYNBENCH_URL + '/v1/models'

PAGE_TITLE = 'DynBench: robust benchmark records generator'
PAGE_ICON  = 'images/dynbench-icon-64.png'
# PAGE_IMAGE = 'images/dynbench-logo-alpha.png'
PAGE_IMAGE = "images/dynbench-logo-alpha-logo-only.png"

LANGUAGES = {  # display name → ISO code
    "English": "en",
    "German": "de",
    "French": "fr",
    "Russian": "ru",
    "Ukrainian": "uk",
    "Italian": "it",
    "Spanish": "es",
    "Polish": "pl",
    "Romanian": "ro",
    "Dutch": "nl",
    "Turkish": "tr",
    "Bavarian": "bar",
    "Portuguese": "pt",
    "Hungarian": "hu",
    "Greek": "el",
    "Czech": "cs",
    "Swedish": "sv",
    "Catalan": "ca",
    "Serbian": "sr",
    "Bulgarian": "bg",
}

LANGUAGE_CODES = {
    code: name for name, code in LANGUAGES.items()
}  # ISO code → display name