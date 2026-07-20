# -*- coding: utf-8 -*-
"""
VocalEdge Clarity Funnel — Automated Backend (v3 - diagnostic logging, no silent fallback)
FIX: the previous version silently returned a hardcoded score=75/pillar="word_stress"
on ANY parsing failure, which looked exactly like a real result. That's why every user
was seeing 75 + "Strategy" regardless of what they said. This version logs the raw Azure
response and raises a real, visible error instead of faking a score, so the actual cause
shows up in Render's logs on the next test.
"""
import os, io, json, time, requests
from flask import Flask, request, jsonify, send_from_directory
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============ CONFIG — pulled from environment variables, set on the host ============
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_REGION = os.environ.get("AZURE_REGION", "centralindia")
FORMSPREE_ENDPOINT = os.environ.get("FORMSPREE_ENDPOINT", "https://formspree.io/f/mwvdzpne")
MANYCHAT_API_KEY = os.environ.get("MANYCHAT_API_KEY", "")

BASELINE_PARAGRAPH = (
    "I wanted to follow up on our conversation from yesterday. Our development "
    "team is finalizing the strategy, and I think it's necessary to address "
    "this before the next review. Could you share your advice on the best "
    "approach? I'm available anytime this week to discuss the value this adds."
)

# ============ PILLAR -> VIDEO LOOKUP ============
VIDEO_LOOKUP = {
    "v_w": {"title": '"Value" - The V Sound', "url": "PASTE_REAL_YOUTUBE_URL_HERE", "issue": "Your V sounds like a W",
            "detail": "In words like 'very' and 'value', try touching your top teeth to your bottom lip before adding your voice."},
    "z_s": {"title": "Zoo or Sue? (Z vs S Fix)", "url": "PASTE_REAL_YOUTUBE_URL_HERE", "issue": "Your Z sounds like an S",
            "detail": "Same mouth shape as S - the only difference is switching your voice on for Z."},
    "th": {"title": "One TH Fix, Four Words Solved", "url": "PASTE_REAL_YOUTUBE_URL_HERE", "issue": "Your TH is landing as a T or D",
           "detail": "Tongue tip lightly between your teeth, then blow air - that's the TH sound."},
    "word_stress": {"title": "Say 'Strategy' Like a Native", "url": "PASTE_REAL_YOUTUBE_URL_HERE", "issue": "Your word stress is shifting meaning",
                     "detail": "English relies on stress placement to carry meaning - one syllable landing wrong changes how clearly the whole word lands."},
    "schwa": {"title": "You're Over-Saying 'Temperature'", "url": "PASTE_REAL_YOUTUBE_URL_HERE", "issue": "You're pronouncing every syllable in full",
              "detail": "Fluent speakers soften unstressed vowels to a quick 'uh' - saying every syllable fully is what sounds effortful, not sounding every letter."},
}

PHONEME_PILLAR_MAP = {
    "v": "v_w", "w": "v_w",
    "z": "z_s", "s": "z_s",
    "th": "th", "dh": "th",
}

# ============ CORE PIPELINE ============

def score_with_azure(audio_url):
    audio_resp = requests.get(audio_url, timeout=30)
    audio_bytes = audio_resp.content

    pron_assessment_config = {
        "ReferenceText": BASELINE_PARAGRAPH,
        "GradingSystem": "HundredMark",
        "Granularity": "Phoneme",
        "EnableMiscue": True,
    }
    import base64
    pa_header = base64.b64encode(json.dumps(pron_assessment_config).encode()).decode()

    url = f"https://{AZURE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    params = {"language": "en-IN", "format": "detailed"}
    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        "Pronunciation-Assessment": pa_header,
        "Accept": "application/json",
    }
    resp = requests.post(url, params=params, headers=headers, data=audio_bytes, timeout=30)
    resp.raise_for_status()
    return resp.json()

def find_weakest_pillar(azure_result):
    """Walk the Azure PA word/phoneme breakdown, find the lowest-scoring phoneme category,
    map it to one of our 5 pillars. Raises (does NOT silently fall back) if the response
    shape isn't what's expected - a silent 75/word_stress fallback previously masked every
    real failure and looked like a genuine score. Log everything so failures are diagnosable."""
    print(f"[DIAGNOSTIC] Raw Azure response: {json.dumps(azure_result)[:2000]}")

    nbest_list = azure_result.get("NBest", [])
    if not nbest_list:
        raise ValueError(f"Azure returned no NBest results. Full response: {azure_result}")
    nbest = nbest_list[0]

    words = nbest.get("Words", [])
    if not words:
        raise ValueError(f"Azure returned NBest but no Words array. NBest content: {nbest}")

    phoneme_scores = {}
    total_phonemes_seen = 0
    unmapped_phonemes = set()
    for w in words:
        for p in w.get("Phonemes", []):
            total_phonemes_seen += 1
            ph = p.get("Phoneme", "").lower()
            score = p.get("AccuracyScore", 100)
            if ph in PHONEME_PILLAR_MAP:
                pillar = PHONEME_PILLAR_MAP[ph]
                phoneme_scores.setdefault(pillar, []).append(score)
            else:
                unmapped_phonemes.add(ph)

    print(f"[DIAGNOSTIC] Words parsed: {len(words)}, phonemes seen: {total_phonemes_seen}, "
          f"mapped pillars found: {list(phoneme_scores.keys())}, unmapped phonemes: {unmapped_phonemes}")

    overall = nbest.get("AccuracyScore")
    if overall is None:
        raise ValueError(f"Azure response has no overall AccuracyScore. NBest keys: {list(nbest.keys())}")

    if phoneme_scores:
        avg_scores = {p: sum(s)/len(s) for p, s in phoneme_scores.items()}
        weakest = min(avg_scores, key=avg_scores.get)
        return weakest, round(overall)

    print(f"[DIAGNOSTIC] No phoneme scores mapped to a pillar - real overall score was {overall}, "
          f"using word_stress as pillar default but this score IS real, not a hardcoded fallback")
    return "word_stress", round(overall)

# ============ CARD GENERATOR (kept for reference, not on the primary webpage path) ============

def wrap(draw, text, font, max_w):
    words = text.split(" "); lines, cur = [], ""
    for w in words:
        t = (cur+" "+w).strip()
        if draw.textlength(t, font=font) <= max_w: cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def draw_ring(d, cx, cy, r, thickness, pct, bg_color, fg_color):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=bg_color, width=thickness)
    start = -90
    end = start + int(360 * pct)
    d.arc([cx-r, cy-r, cx+r, cy+r], start=start, end=end, fill=fg_color, width=thickness)

def generate_card(name, score_pct, issue_headline, issue_detail, video_title):
    GF = "/usr/share/fonts/truetype/google-fonts/"
    BOLD, MEDIUM, REGULAR = GF+"Poppins-Bold.ttf", GF+"Poppins-Medium.ttf", GF+"Poppins-Regular.ttf"
    TEAL=(14,107,96); TEAL_BRIGHT=(25,179,154); TEAL_WASH=(234,244,241)
    INK=(16,19,24); OFFWHITE=(250,250,248); WHITE=(255,255,255); DIM=(92,102,114)
    W, H, S = 1080, 1580, 2

    img = Image.new("RGB", (W*S, H*S), OFFWHITE)
    d = ImageDraw.Draw(img)
    M = int(0.08*W*S)

    band_h = int(0.10*H*S)
    d.rectangle([0,0,W*S,band_h], fill=INK)
    wm_path = os.path.join(os.path.dirname(__file__), "sys", "wm_dark.png")
    if os.path.exists(wm_path):
        wm = Image.open(wm_path).convert("RGBA")
        target_w = int(0.30*W*S); ratio = target_w/wm.width
        wm_r = wm.resize((target_w, int(wm.height*ratio)), Image.LANCZOS)
        img.paste(wm_r, (W*S//2 - target_w//2, int(band_h*0.20)), wm_r)

    y = band_h + int(0.05*H*S)
    greet_f = ImageFont.truetype(MEDIUM, 30*S)
    for ln in wrap(d, f"Hey {name}, here's your Clarity Score", greet_f, W*S-2*M):
        lw = d.textlength(ln, font=greet_f)
        d.text(((W*S-lw)//2, y), ln, font=greet_f, fill=DIM); y += 38*S
    y += int(0.03*H*S)

    ring_cx, ring_cy, ring_r = W*S//2, y+int(0.16*H*S), int(0.15*H*S)
    draw_ring(d, ring_cx, ring_cy, ring_r, 14*S, score_pct/100, TEAL_WASH, TEAL_BRIGHT)
    score_f = ImageFont.truetype(BOLD, 90*S)
    sb = d.textbbox((0,0), str(score_pct), font=score_f)
    d.text((ring_cx-(sb[2]-sb[0])//2, ring_cy-(sb[3]-sb[1])//2-sb[1]), str(score_pct), font=score_f, fill=INK)
    pct_f = ImageFont.truetype(MEDIUM, 22*S)
    d.text((ring_cx-d.textlength("out of 100",font=pct_f)//2, ring_cy+int(0.045*H*S)), "out of 100", font=pct_f, fill=DIM)

    y = ring_cy+ring_r+int(0.07*H*S)
    d.line([(M,y),(W*S-M,y)], fill=(216,212,203), width=2*S); y += int(0.045*H*S)

    tag_f = ImageFont.truetype(BOLD, 20*S)
    tw_ = d.textlength("YOUR ONE FOCUS AREA", font=tag_f); pad=16*S
    pill_w, pill_h = tw_+pad*2, 46*S; px = (W*S-pill_w)//2
    d.rounded_rectangle([px,y,px+pill_w,y+pill_h], radius=pill_h//2, fill=TEAL)
    d.text((px+pad,y+11*S), "YOUR ONE FOCUS AREA", font=tag_f, fill=WHITE)
    y += pill_h+int(0.035*H*S)

    head_f = ImageFont.truetype(BOLD, 48*S)
    for ln in wrap(d, issue_headline, head_f, W*S-2*M):
        lw = d.textlength(ln, font=head_f)
        d.text(((W*S-lw)//2,y), ln, font=head_f, fill=INK); y += 58*S
    y += int(0.02*H*S)

    det_f = ImageFont.truetype(REGULAR, 26*S)
    for ln in wrap(d, issue_detail, det_f, W*S-2.6*M):
        lw = d.textlength(ln, font=det_f)
        d.text(((W*S-lw)//2,y), ln, font=det_f, fill=DIM); y += 34*S
    y += int(0.05*H*S)

    box_h = int(0.11*H*S)
    d.rounded_rectangle([M,y,W*S-M,y+box_h], radius=16*S, fill=TEAL_WASH)
    vn_f = ImageFont.truetype(MEDIUM, 20*S)
    d.text((M+30*S,y+18*S), "YOUR MATCHED 30-SECOND LESSON", font=vn_f, fill=TEAL)
    vt_f = ImageFont.truetype(BOLD, 32*S)
    yy = y+52*S
    for ln in wrap(d, video_title, vt_f, W*S-2*M-60*S)[:2]:
        d.text((M+30*S,yy), ln, font=vt_f, fill=INK); yy += 40*S
    y += box_h+int(0.05*H*S)

    d.line([(M,y),(W*S-M,y)], fill=(216,212,203), width=2*S); y += int(0.035*H*S)
    bridge_f = ImageFont.truetype(REGULAR, 24*S)
    bridge = "This score is based on one sentence. Your full Clarity Profile checks every sound - with a new personalized fix every day."
    for ln in wrap(d, bridge, bridge_f, W*S-2.4*M):
        lw = d.textlength(ln, font=bridge_f)
        d.text(((W*S-lw)//2,y), ln, font=bridge_f, fill=DIM); y += 32*S
    y += int(0.025*H*S)

    cta_h = int(0.075*H*S)
    d.rounded_rectangle([M,y,W*S-M,y+cta_h], radius=cta_h//2, fill=TEAL_BRIGHT)
    cta_f = ImageFont.truetype(BOLD, 26*S)
    clw = d.textlength("Start Founding Membership - $6.99/mo", font=cta_f)
    d.text(((W*S-clw)//2, y+int(cta_h*0.28)), "Start Founding Membership - $6.99/mo", font=cta_f, fill=WHITE)
    y += cta_h+int(0.03*H*S)

    tag2_f = ImageFont.truetype(MEDIUM, 22*S)
    lw = d.textlength("Clarity, not accent erasure.", font=tag2_f)
    d.text(((W*S-lw)//2,y), "Clarity, not accent erasure.", font=tag2_f, fill=TEAL)

    out_path = f"/tmp/clarity_card_{int(time.time())}.jpg"
    img.resize((W,H), Image.LANCZOS).save(out_path, quality=95)
    return out_path

# ============ WEBHOOK ENDPOINTS ============

@app.route("/webhook/voice-note", methods=["POST"])
def handle_voice_note():
    """LEGACY - unreachable in the current webpage-based funnel. Kept for reference only."""
    data = request.json
    name = data.get("first_name", "there")
    audio_url = data.get("audio_url")
    subscriber_id = data.get("subscriber_id")

    if not audio_url:
        return jsonify({"error": "no audio_url provided"}), 400

    try:
        azure_result = score_with_azure(audio_url)
        pillar, overall_score = find_weakest_pillar(azure_result)
        video = VIDEO_LOOKUP.get(pillar, VIDEO_LOOKUP["word_stress"])
        card_path = generate_card(name, overall_score, video["issue"], video["detail"], video["title"])
        return jsonify({
            "status": "scored", "subscriber_id": subscriber_id, "score": overall_score,
            "pillar": pillar, "video_title": video["title"], "card_path": card_path,
        })
    except Exception as e:
        print(f"Pipeline error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/score", methods=["POST", "OPTIONS"])
def api_score():
    """PRIMARY PATH. Direct browser upload endpoint for clarity_score_page.html.
    Accepts multipart/form-data with an 'audio' file and a 'name' field, returns JSON."""
    if request.method == "OPTIONS":
        return _cors_preflight()

    if "audio" not in request.files:
        return _cors(jsonify({"error": "no audio file provided"})), 400

    name = request.form.get("name", "there")
    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    print(f"[DIAGNOSTIC] Received audio upload: {len(audio_bytes)} bytes, filename={audio_file.filename}, "
          f"content_type={audio_file.content_type}")

    try:
        pron_assessment_config = {
            "ReferenceText": BASELINE_PARAGRAPH,
            "GradingSystem": "HundredMark",
            "Granularity": "Phoneme",
            "EnableMiscue": True,
        }
        import base64
        pa_header = base64.b64encode(json.dumps(pron_assessment_config).encode()).decode()
        url = f"https://{AZURE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        params = {"language": "en-IN", "format": "detailed"}
        headers = {
            "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Pronunciation-Assessment": pa_header,
            "Accept": "application/json",
        }
        resp = requests.post(url, params=params, headers=headers, data=audio_bytes, timeout=30)
        print(f"[DIAGNOSTIC] Azure HTTP status: {resp.status_code}")
        resp.raise_for_status()
        azure_result = resp.json()

        pillar, overall_score = find_weakest_pillar(azure_result)
        video = VIDEO_LOOKUP.get(pillar, VIDEO_LOOKUP["word_stress"])

        return _cors(jsonify({
            "status": "ok",
            "name": name,
            "score": overall_score,
            "issue_headline": video["issue"],
            "issue_detail": video["detail"],
            "video_title": video["title"],
            "video_url": video["url"],
        }))
    except Exception as e:
        import traceback
        print(f"[ERROR] api_score failed: {e}")
        print(traceback.format_exc())
        return _cors(jsonify({"error": "Could not score that recording. Please try again.", "debug": str(e)})), 500

def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

def _cors_preflight():
    resp = jsonify({"status": "ok"})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.route("/webhook/capture-email", methods=["POST"])
def capture_email():
    data = request.json
    email = data.get("email")
    if not email or "@" not in email:
        return jsonify({"error": "invalid email"}), 400
    try:
        resp = requests.post(FORMSPREE_ENDPOINT, data={"email": email, "source": "clarity_funnel_page"}, timeout=15)
        return jsonify({"status": "captured", "formspree_status": resp.status_code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def serve_score_page():
    """Render serves clarity_score_page.html directly (single-deploy option) -
    no separate GitHub Pages host needed. The page itself calls /api/score,
    which lives on this same origin, so no CORS round-trip is even required
    in this configuration (CORS headers are still sent regardless, in case
    the page is ever hosted elsewhere instead)."""
    return send_from_directory(BASE_DIR, "clarity_score_page.html")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "azure_key_set": bool(AZURE_SPEECH_KEY)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
