"""Testlerin ortak malzemesi: gecerli bir senaryo ve sahte Gemini."""
import copy
import itertools

SCENES = ("title", "contrast", "table", "bars", "counter", "split",
          "timeline", "byte_says", "close",
          "steps", "flow", "equation", "ring", "dots", "chat", "terminal", "tokens",
          "probs", "layers", "checklist", "headline", "scale", "cycle", "bits", "guess")
THEMES = ("midnight", "ember", "deep", "moss", "slate", "plum", "rust", "ice")


def good_spec() -> dict:
    """Tum kurallardan gecen, 11 beat'lik senaryo."""
    return copy.deepcopy({
        "format": "measured",
        "title": "A minute of AI video costs sixty seconds of money",
        "summary": "Video models bill by the second, so length sets the bill.",
        "tags": ["pricing", "video"],
        "sources": ["Veo public pricing page", "Provider pricing table"],
        "beats": [
            {"id": "b1", "role": "hook", "scene": "contrast",
             "say": "One second of video costs more than this whole channel.",
             "cap": "$0.40 vs $0.00",
             "data": {"left": {"label": "this video", "value": "$0.00"},
                      "right": {"label": "1 s of Veo", "value": "$0.40",
                                "tone": "bad"},
                      "verdict": "Same screen."}},
            {"id": "b2", "role": "why",
             "say": "Video models bill by the second, not by the clip.",
             "cap": "billed per second"},
            {"id": "b3", "role": "why", "scene": "counter",
             "say": "A minute therefore costs sixty times the second.",
             "cap": "$0.40 x 60 = $24",
             "data": {"prefix": "$", "from": 0, "to": 24, "dp": 0,
                      "note": "60 s x $0.40"}},
            {"id": "b4", "role": "data", "scene": "table",
             "say": "Here is the same minute at three price points.",
             "cap": "price of 60 seconds",
             "data": {"rows": [
                 {"name": "code render", "value": "$0", "ratio": 0.02},
                 {"name": "cheap model", "value": "$3", "ratio": 3,
                  "tone": "mid"},
                 {"name": "top model", "value": "$24", "ratio": 24,
                  "tone": "bad"}]}},
            {"id": "b5", "role": "data",
             "say": "The cheapest model charges three dollars for it.",
             "cap": "$3"},
            {"id": "b6", "role": "data",
             "say": "The top model charges twenty four.", "cap": "$24"},
            {"id": "b7", "role": "data",
             "say": "This video was drawn by code and costs nothing.",
             "cap": "$0 to render"},
            {"id": "b8", "role": "turn", "scene": "byte_says",
             "say": "But free is the strange number here.",
             "cap": "free is the outlier",
             "data": {"pose": "shrug", "cursor": "amber",
                      "line": "Free is the strange one."}},
            {"id": "b9", "role": "turn",
             "say": "Every other row grows with the length of the clip.",
             "cap": "price grows with length"},
            {"id": "b10", "role": "resolve",
             "say": "Length sets the bill for video models.",
             "cap": "length sets the bill"},
            {"id": "b11", "role": "resolve", "scene": "close",
             "say": "BYTE measures. That is all.", "cap": "BYTE",
             "data": {"lines": ["Length sets the bill."]}},
        ],
    })


CLAIMS = [
    {"shown": "$0.40", "expr": None, "value": None, "source": 0},
    {"shown": "$24", "expr": "0.40*60", "value": 24, "source": None},
    {"shown": "60 seconds", "expr": "1*60", "value": 60, "source": None},
    {"shown": "$3", "expr": "0.05*60", "value": 3, "source": None},
]


def review(verdict="publish", score=8, risk="low", fixes=None, claims=None,
           facts=None):
    return {"scores": {k: score for k in
                       ("hook", "story", "clarity", "audience", "voice")},
            "notes": {}, "risk": {"level": risk, "flags": []},
            "claims": CLAIMS if claims is None else claims,
            "facts": facts or [],
            "verdict": verdict, "fixes": fixes or []}


def copy_parts():
    return {"titles": ["A minute of AI video costs $24 at the top end",
                       "Video models bill by the second",
                       "Sixty seconds of AI video, priced",
                       "What a minute of AI video costs"],
            "best": 1,
            "youtube": {"hook": "Video models bill per second, so a minute "
                                "costs sixty times the second."},
            "instagram": {"caption": "Video models bill by the second."},
            "tiktok": {"caption": "A minute of AI video, priced."},
            "hashtags": {"youtube": ["#aivideo", "#pricing", "#ai"],
                         "instagram": ["#aivideo", "#pricing"],
                         "tiktok": ["#aivideo"]}}


class FakeLLM:
    """Gemini yerine gecen, rol basina siraya dizilmis cevaplar."""
    model = "gemini-fake-flash"
    last_grounded = True

    def __init__(self, replies: dict):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.log = []
        self.calls = 0

    def ask_json(self, prompt, **kw):
        role = kw.get("role", "")
        self.calls += 1
        self.log.append((role, prompt))
        q = self.replies.get(role)
        if not q:
            return None
        return q.pop(0) if len(q) > 1 else q[0]


def counter():
    c = itertools.count()
    return lambda: float(next(c))


def story_form() -> dict:
    """Panelin kolay formunun GECERLI bir ornegi (12 cumle, 2 kaynak, 5 olay). Rakamlar olay
    satirlarinda da yazili: ekrandaki her anlamli sayi bir olay satirina baglanir."""
    beats = [
        ("YouTube started as a video dating site.", "YouTube began as a dating site", "", ""),
        ("Its tagline was tune in, hook up.", "Tagline: Tune in, hook up", "Tune in, hook up", ""),
        ("The domain was registered on Valentine's Day, two thousand five.",
         "Domain registered: Feb 14, 2005", "Feb 14, 2005", ""),
        ("The first video went up in April two thousand five.", "First video: Apr 2005", "Apr 2005", ""),
        ("Users quickly began posting videos on any subject.", "Videos on any subject", "any subject", ""),
        ("By December two thousand five, it reported eight million views a day.",
         "Dec 2005: 8M views a day", "8M views", ""),
        ("By October two thousand six, it reported over one hundred million views a day.",
         "Oct 2006: 100M+ views a day", "100M+", ""),
        ("Google agreed to acquire it that month.", "Google agrees to acquire it", "", ""),
        ("The price was one billion, six hundred fifty million dollars.",
         "$1.65 billion deal", "$1.65 billion", "check"),
        ("That was about twenty months after the company was founded.",
         "About 20 months after founding", "20 months", ""),
        ("A dating site idea became a video platform.", "Dating idea. Video platform.", "", ""),
        ("Google bought that platform.", "Bought by Google", "", ""),
    ]
    return {
        "title": "YouTube started as a video dating site", "format": "story", "theme": "",
        "tags": "youtube, startup story, google",
        "description": ("YouTube began in 2005 as a video dating site with the tagline 'Tune in, hook up'. "
                        "Google agreed to buy it in October 2006 for $1.65 billion."),
        "beats": [{"say": a, "cap": b, "kw": c, "mark": d} for a, b, c, d in beats],
        "sources": ["https://www.mediavillage.com/article/historys-moment-in-media-youtubes-origin-story/",
                    "https://www.sec.gov/Archives/edgar/data/1288776/000119312506206884/dex991.htm"],
        "facts": [
            {"text": "YouTube began as a dating site where users uploaded videos about themselves; "
                     "its tagline was 'Tune in, hook up'",
             "source": 1, "note": "MediaVillage: began as a dating site; tagline 'Tune in, hook up'"},
            {"text": "The YouTube domain was registered on February 14, 2005 and the first video was posted in "
                     "April 2005", "source": 1,
             "note": "MediaVillage: registered on Valentine's Day 2005; first video April 2005"},
            {"text": "In December 2005 YouTube reported 8 million views a day", "source": 1,
             "note": "MediaVillage: came out of beta in December 2005 with 8 million views a day"},
            {"text": "On October 9, 2006 Google agreed to buy YouTube for $1.65 billion in stock; YouTube had "
                     "more than 100 million views a day", "source": 2,
             "note": "Google press release, October 9, 2006: $1.65 billion; more than 100 million views"},
            {"text": "Google bought YouTube about 20 months after it was founded", "source": 2,
             "note": "Google press release: founded February 2005, deal October 2006"},
        ],
        "calcs": [],
    }
