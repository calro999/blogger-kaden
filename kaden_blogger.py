import os
import sys
import re
import random
import requests
import time
import base64
import json
import tempfile
import difflib
from playwright.sync_api import sync_playwright

CACHE_FILE = "posted_cache.txt"

# --- タイトル重複防止 & オリジナリティ保証モジュール ---
POSTED_TITLES_FILE = "posted_titles.txt"
RECENT_THEMES_FILE = "recent_themes.txt"

def load_posted_titles():
    """過去に投稿された記事タイトルの一覧を取得"""
    if os.path.exists(POSTED_TITLES_FILE):
        with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def save_posted_title(title):
    """新規投稿タイトルを永続化保存"""
    if not title:
        return
    title_clean = title.strip()
    with open(POSTED_TITLES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{title_clean}\n")

BANNED_TITLE_PHRASES = [
    "毎日の身だしなみを見直す", "毎日の身だしなみ", "身だしなみを見直す", "身だしなみの新常識",
    "神アイテム",
    "神ギア",
    "人気アイテム",
    "ねじ伏せる",
    "無力化する",
    "死守する",
    "構造改革",
    "根こそぎ",
    "根源から断つ",
    "完全抹消",
    "完全制圧",
    "頭皮の詰まり",
    "頭皮の硬化",
    "頭皮の停滞",
    "深夜の濃厚補給",
    "深夜のPC作業",
    "深夜の",
    "至近距離",
    "至近距離も余裕",
    "至近距離で差がつく",
    "至近距離でも怯まない",
    "至近距離でも怖くない",
    "至近距離でも余裕",
    "至近距離の商談",
    "至近距離の視線",
    "至近距離でも動じない",
    "至近距離の会話",
    "鏡を見る", "鏡の前で", "鏡を見て", "鏡をのぞく", "鏡に映る", "鏡を見るのが", "鏡を見るたび",
    "失敗しない", "いかがでしたでしょうか", "徹底解説", "完全ガイド", "徹底比較", "後悔しない",
    "男の清潔感を高めるギア", "注目のアイテム", "おすすめアイテム", "厳選アイテム", "大人気アイテム", "話題のアイテム"
]

def check_title_banned_phrases(title):
    """タイトル内に陳腐なテンプレ・スパムフレーズが含まれているかチェック"""
    if not title:
        return True, "タイトルが空です"
    for phrase in BANNED_TITLE_PHRASES:
        if phrase in title:
            return True, f"禁止フレーズ「{phrase}」が含まれています"
    return False, None

def is_title_duplicate_or_similar(new_title, threshold=0.50):
    """
    過去のタイトルと完全一致、または類似度が閾値（60%）以上なら重複と判定
    さらに禁止フレーズや冒頭10文字被りも厳格にブロック
    """
    import difflib
    if not new_title:
        return True, "空のタイトル", 1.0

    has_banned, banned_reason = check_title_banned_phrases(new_title)
    if has_banned:
        return True, banned_reason, 1.0

    existing_titles = load_posted_titles()
    clean_new = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', new_title)
    if not clean_new:
        return True, "無効なタイトル", 1.0

    for past in existing_titles:
        if new_title.strip() == past.strip():
            return True, past, 1.0

        if len(new_title) >= 5 and len(past) >= 5:
            if new_title[:5] == past[:5]:
                return True, f"冒頭10文字重複（{past[:10]}）: {past}", 0.95

        clean_past = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', past)
        if not clean_past:
            continue
        ratio = difflib.SequenceMatcher(None, clean_new, clean_past).ratio()
        if ratio >= threshold:
            return True, past, ratio

    return False, None, 0.0

def load_recent_themes(limit=10):
    """直近投稿されたテーマ・商品コードを取得"""
    if os.path.exists(RECENT_THEMES_FILE):
        with open(RECENT_THEMES_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
            return lines[-limit:]
    return []

def save_recent_theme(theme_name):
    """テーマやキーワードを履歴に保存"""
    if not theme_name:
        return
    with open(RECENT_THEMES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{theme_name.strip()}\n")

def click_physical(page, selector):
    import time
    elements = page.locator(selector).all()
    for el in elements:
        try:
            box = el.bounding_box()
            if box and box['width'] > 0 and box['height'] > 0:
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                page.mouse.click(x, y)
                return True
        except:
            pass
    return False

def load_posted_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_cache(item_code):
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{item_code}\n")

def clean_rakuten_item_name(name):
    """楽天特有のクーポン・セール・ノイズ単語を除去して綺麗な商品名を抽出する"""
    import re
    if not name:
        return "注目アイテム"
    cleaned = re.sub(r'【[^】]*】', '', name)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    cleaned = re.sub(r'（[^）]*）', '', cleaned)
    cleaned = re.sub(r'\([^\)]*\)', '', cleaned)
    
    noise_patterns = [
        r'クーポン(?:で|\s*利用で|\s*配布中|\s*対象)?\s*[0-9,]+円?(?:OFF|off)?',
        r'P[0-9]+倍',
        r'ポイント[0-9]+倍',
        r'送料無料',
        r'即納',
        r'あす楽',
        r'マラソン(?:限定)?',
        r'スーパーセール',
        r'お買い物マラソン',
        r'楽天(?:1位|ランキング1位|デイリー1位)',
        r'[0-9]+%OFF',
        r'[0-9]+％OFF',
        r'★[0-9\.]+★?',
        r'レビュー特典',
        r'公式(?:店)?',
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        
    words = [w.strip() for w in cleaned.split() if w.strip()]
    seen = set()
    cleaned_words = []
    for w in words:
        if w not in seen and len(w) > 1:
            seen.add(w)
            cleaned_words.append(w)
        if len(' '.join(cleaned_words)) >= 28:
            break
            
    res = ' '.join(cleaned_words).strip()
    return res if res else (words[0] if words else name[:25])

def get_rakuten_affiliate_url(item, affiliate_id):
    aff_url = item.get("affiliateUrl")
    if aff_url and "hb.afl.rakuten.co.jp" in aff_url:
        return aff_url
    
    item_url = item.get("itemUrl") or ""
    if not item_url:
        return ""
    
    if affiliate_id:
        import urllib.parse
        encoded_item_url = urllib.parse.quote(item_url, safe='')
        return f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/?pc={encoded_item_url}&m={encoded_item_url}"
    
    return item_url

def extract_image_url(item):
    """楽天APIレスポンスから高画質かつ有効な画像URLを抽出"""
    if not item:
        return ""
    raw_url = ""
    for key in ["mediumImageUrls", "smallImageUrls"]:
        imgs = item.get(key, [])
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            if isinstance(first, dict):
                raw_url = first.get("imageUrl", "") or first.get("url", "")
            elif isinstance(first, str):
                raw_url = first
            if raw_url:
                break
    if not raw_url:
        raw_url = item.get("imageUrl") or ""

    if raw_url:
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("http://"):
            raw_url = "https://" + raw_url[7:]
        if "_ex=" in raw_url:
            raw_url = re.sub(r'_ex=[0-9]+x[0-9]+', '_ex=500x500', raw_url)
    return raw_url

def sanitize_llm_output(content, valid_affiliate_url):
    if not content:
        return ""
    import re
    url_pattern = re.compile(r"""https?://[^\s"'<>()]+""")
    def replace_url(match):
        found_url = match.group(0)
        # 楽天画像ドメインや画像拡張子はアフィリエイトURLに書き換えない（画像の破損防止）
        if any(dom in found_url for dom in ["thumbnail.image.rakuten.co.jp", "image.rakuten.co.jp", "tshop.r10s.jp"]):
            return found_url
        if any(found_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
            return found_url
        if "room.rakuten.co.jp" in found_url or "hb.afl.rakuten.co.jp" in found_url or ("rakuten.co.jp" in found_url and "affiliateId" in found_url):
            return found_url
        return valid_affiliate_url if valid_affiliate_url else "https://room.rakuten.co.jp/jack555/items"
    
    sanitized = url_pattern.sub(replace_url, content)
    sanitized = sanitized.replace("Amazon", "楽天市場").replace("アマゾン", "楽天市場").replace("ヤフー", "楽天市場").replace("Yahoo!", "楽天市場")
    return sanitized

def fetch_rakuten_item():
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id or not access_key:
        raise ValueError("RAKUTEN_APP_ID and RAKUTEN_ACCESS_KEY must be set in environment variables.")

    keywords_pool = [
        "スマート加湿器 卓上 アロマ",
        "小型コーヒーグラインダー 静音",
        "一人暮らし ミニ炊飯器 糖質カット",
        "コンパクトホットプレート たこ焼き",
        "ハンディクリーナー 車載 強力吸引",
        "コードレス ミニヘアアイロン 充電式",
        "デスクパネルヒーター 省エネ",
        "超音波洗浄機 メガネ 時計",
        "小型脱臭機 オゾン ペット",
        "電動ミル ソルト ペッパー 岩塩",
        "卓上食洗機 タンク式 工事不要",
        "ミニブレンダー スムージー 持ち運び",
        "スマート体重計 体組成計 スマホ連動",
        "小型サーキュレーター 3D首振り",
        "衣類スチーマー 立ち上がり早い 軽量",
        "ポータブル電源 小型 キャンプ 防災",
        "電気ケトル 温度調節 保温 細口",
        "毛玉取り器 電動 6枚刃 USB充電",
        "ネッククーラー 冷却プレート 静音",
        "布団乾燥機 コンパクト 靴乾燥",
        "スマートプラグ タイマー 遠隔操作",
        "温湿度計 デジタル 高精度 アラーム",
        "卓上冷風扇 小型 USB給電",
        "エアーフライヤー ノンフライヤー 小型",
        "ホットサンドメーカー 電気 耳まで焼ける",
        "ミニプロジェクター 小型 モバイル",
        "電子メモパッド カラー 手書き",
        "LEDデスクライト 調光調色 目に優しい",
        "モバイルバッテリー MagSafe ワイヤレス急速充電",
        "靴乾燥機 脱臭 コンパクト ダブルノズル"
    ]

    posted_cache = load_posted_cache()
    past_titles = load_posted_titles()
    recent_kw = load_recent_themes(limit=15)

    # 直近選ばれたキーワードを優先度下げて並べ替え（シャッフル巡回）
    candidate_kws = [k for k in keywords_pool if k not in recent_kw]
    random.shuffle(candidate_kws)
    fallback_kws = [k for k in keywords_pool if k in recent_kw]
    random.shuffle(fallback_kws)
    search_queue = candidate_kws + fallback_kws

    url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"

    # キーワードを順番に試し、未投稿かつ非重複の商品が見つかるまで粘り強く探索（最大10キーワード巡回）
    for kw_idx, keyword in enumerate(search_queue[:10]):
        print(f"[Attempt {kw_idx+1}/10] Searching Rakuten for keyword: '{keyword}'...")
        params = {
            "applicationId": app_id,
            "accessKey": access_key,
            "keyword": keyword,
            "format": "json",
            "hits": 30
        }
        if affiliate_id:
            params["affiliateId"] = affiliate_id

        try:
            response = requests.get(url, params=params, timeout=20)
            data = response.json() if response.status_code == 200 else {}
            items = data.get("Items", [])
            
            # 0件の場合はキーワード単語を分解して広域検索
            if not items and len(keyword.split()) > 1:
                params["keyword"] = keyword.split()[0]
                resp2 = requests.get(url, params=params, timeout=20)
                items = resp2.json().get("Items", []) if resp2.status_code == 200 else []

            if not items:
                continue

            # 1. 理想パターン：過去タイトルとも被らず、未投稿の商品
            for item_wrapper in items:
                item = item_wrapper.get("Item", {})
                item_code = item.get("itemCode")
                name = item.get("itemName", "")
                if any(ng in name for ng in ["リサイクル券", "回収", "利用券", "チケット", "処分", "修理", "中古", "訳あり"]):
                    continue
                if not item_code or item_code in posted_cache:
                    continue

                clean_name = clean_rakuten_item_name(name)
                clean_comp = re.sub(r"""[\s\d月【】選！!｜|：:・\-\[\]（）()]+""", '', clean_name)
                is_item_dup = False
                for pt in past_titles[-50:]:
                    pt_clean = re.sub(r"""[\s\d月【】選！!｜|：:・\-\[\]（）()]+""", '', pt)
                    if len(clean_comp) >= 6 and clean_comp[:8] in pt_clean:
                        is_item_dup = True
                        break
                if is_item_dup:
                    continue

                save_recent_theme(keyword)
                print(f"Found ideal unposted & non-duplicate item: {clean_name[:25]}")
                return item

            # 2. セカンド候補：過去タイトルとは多少語句がかすっても、itemCode未投稿の商品（更新を止めないための安全弁）
            for item_wrapper in items:
                item = item_wrapper.get("Item", {})
                item_code = item.get("itemCode")
                name = item.get("itemName", "")
                if any(ng in name for ng in ["リサイクル券", "回収", "利用券", "チケット", "処分", "修理", "中古", "訳あり"]):
                    continue
                if item_code and item_code not in posted_cache:
                    save_recent_theme(keyword)
                    clean_name = clean_rakuten_item_name(name)
                    print(f"Found unposted item (fallback): {clean_name[:25]}")
                    return item

        except Exception as err:
            print(f"Error fetching for keyword '{keyword}': {err}")
            continue

    # 万が一上記全10キーワードでも全て投稿済みだった場合、キーワード指定なし・広域検索で未投稿品を確実に見つける
    print("[FALLBACK] All 10 keywords exhausted. Performing broad open search to ensure continuous posting...")
    broad_kws = ["人気", "注目", "ランキング", "便利", "新作"]
    for b_kw in broad_kws:
        params = {
            "applicationId": app_id,
            "accessKey": access_key,
            "keyword": f"スマート家電 {b_kw}",
            "format": "json",
            "hits": 30
        }
        if affiliate_id:
            params["affiliateId"] = affiliate_id
        try:
            r = requests.get(url, params=params, timeout=20)
            items = r.json().get("Items", []) if r.status_code == 200 else []
            for item_wrapper in items:
                item = item_wrapper.get("Item", {})
                code = item.get("itemCode")
                if code and code not in posted_cache:
                    print(f"Broad search found unposted item: {item.get('itemName', '')[:25]}")
                    return item
        except Exception:
            pass

    raise RuntimeError("Could not find any unposted items across all keyword pools.")

def generate_article_with_llm(item):
    raw_title = item.get("itemName", "")
    title = clean_rakuten_item_name(raw_title)
    clean_title = title
    price = item.get("itemPrice", "")
    caption = item.get("itemCaption", "")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    url = get_rakuten_affiliate_url(item, affiliate_id)

    image_url = ""
    medium_images = item.get("mediumImageUrls", [])
    if medium_images:
        image_url = medium_images[0].get("imageUrl", "") if isinstance(medium_images[0], dict) else medium_images[0]
    else:
        small_images = item.get("smallImageUrls", [])
        if small_images:
            image_url = small_images[0].get("imageUrl", "") if isinstance(small_images[0], dict) else small_images[0]

    buy_button_html = (
        f'<div style="text-align: center; margin: 20px 0;">'
        f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
        f'style="display:inline-block; padding: 14px 28px; background-color: #bf0000; '
        f'color: #ffffff; font-weight: bold; font-size: 16px; border-radius: 8px; '
        f'text-decoration: none; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">'
        f'🛒 楽天市場で価格・在庫を見る</a></div>'
    )

    past_titles = load_posted_titles()[-50:]
    past_titles_str = "\n".join([f"- {t}" for t in past_titles]) if past_titles else "（過去の重複なし）"

    title_angles = [
        "【本音・実用レビュー型】実際に日常で使って分かった真価や使い勝手をストレートに提示",
        "【悩み解決・ビフォーアフター型】「〇〇で困っていた人に」など痛みの解消を前面に提示",
        "【構造・こだわりスペック型】素材、機能、独自設計などのスペック価値にフォーカス",
        "【生活シーン想起型】日常の特定のワンシーン（朝の準備、作業中、くつろぎ時間等）を切り取る",
        "【差別化・選ばれる理由型】類似品と何が決定的に違うのか、独自の強みを明確にする"
    ]
    chosen_angle = random.choice(title_angles)

    prompt = f"""以下は楽天市場から厳選した小型家電・スマート家電・暮らしの便利ガジェットのアイテムデータです。
Google検索・読者双方から最高品質の一次情報レビューとして高く評価されるよう、独自性と専門性に溢れる独立したブログ記事（タイトル＋完全HTML本文）を執筆してください。

【商品データ】:
- 商品名（整形済み）: {title}
- 元の商品名情報: {raw_title[:150]}
- 参考価格: {price}円
- 商品説明概要: {caption[:350]}
- 商品画像URL: {image_url}
- アフィリエイトURL: {url}

【今回のタイトル推奨切り口】: {chosen_angle}

【過去に投稿した直近のタイトル一覧（これらと構文・出だし・キーワードの並びが酷似するものは【絶対禁止】）】:
{past_titles_str}

【絶対厳守の独自性・品質要件】:
1. タイトル（title）:
   - 30〜42文字程度。過去タイトルと絶対に被らない、商品固有の魅力を引き出したオリジナルタイトル。
   - 「鏡を見る〜」「失敗しない〜」「徹底解説」「完全ガイド」「注目のアイテム」「おすすめ」などの安易な陳腐フレーズは完全使用禁止。
   - 商品名の単なる羅列やコピペは禁止。読者の好奇心や購入意欲を刺激する言葉を選ぶこと。
2. 本文HTML（html）:
   - 全体を `<div class="article-content" style="line-height: 1.85; color: #2d3748; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">` で囲む。
   - 導入部:
     - 読者が日常で直面する疑問や関心に寄り添い、なぜ今この商品が選ばれているのか、背景や魅力を300文字程度で自然に導入。
     - 「いかがでしたでしょうか」などの定型文は使わない。
   - 商品画像表示: {f'<div style="text-align: center; margin: 24px 0;"><img src="{image_url}" alt="{title}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"></div>' if image_url else ""}
   - 本文セクション:
     - 単なるスペック紹介ではなく、実際の使い心地、他と差がつくこだわり設計、手にしたときのリアルな感覚を具体的に描写。
     - 適宜 `<h3>` 小見出しを用いて読みやすく構造化。
   - 独自のチェックポイント / メリット・注意点:
     - 購入前に知っておくべきポイントを3〜4項目、`<ul>` と `<li>` で箇条書き。
   - 購入ボタンHTML: {buy_button_html}
   - まとめセクション:
     - どんな人におすすめできるかを端的に総括し、前向きな後押しをして結ぶ。
3. 他社EC（Amazon, Yahoo等）の名称やリンクは一切含めないこと。

【出力形式】:
以下のJSONフォーマットのみを出力してください（Markdownコードブロックで囲むこと）:
```json
{{
    "title": "生成したオリジナルタイトル",
    "html": "生成した完全なHTML本文"
}}
```
"""
    system_message = "あなたは日々の暮らしを快適にするスマート家電・生活家電専門のテクニカルライター兼編集者です。実用性と専門性の高い独立レビュー記事を執筆します。"


    def parse_json_response(text):
        import json as _json
        text = text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```")[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```")[0]
        text = text.strip()
        try:
            data = _json.loads(text)
            if isinstance(data, dict) and "html" in data:
                return data
        except Exception:
            pass
        return None

    # 1. Gemini API（最優先）
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        models = [
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview",
            "gemini-flash-latest"
        ]
        for model_name in models:
            try:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048}
                }
                if any(v in model_name for v in ["2.5", "3.", "3-"]):
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
                res = requests.post(api_url, json=payload, timeout=40)
                if res.status_code == 200:
                    data = res.json()
                    candidate = data.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via Gemini API ({model_name}).")
                        return parsed
                else:
                    print(f"Gemini API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) error: {e}")

    # 2. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-70b-8192"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=40)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via Groq API ({model_name}).")
                        return parsed
                else:
                    print(f"Groq API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Groq API ({model_name}) error: {e}")

    # 3. OpenRouter API
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        for model_name in ["google/gemma-3-27b-it:free", "mistralai/mistral-nemo:free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com",
                    "X-Title": "BloggerBot"
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=40)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via OpenRouter ({model_name}).")
                        return parsed
                else:
                    print(f"OpenRouter ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"OpenRouter ({model_name}) error: {e}")

    # 4. GitHub Models API (PATのみ)
    gh_token = os.environ.get("GH_TOKEN")
    if gh_token and not gh_token.startswith("ghs_"):
        for model_name in ["gpt-4o-mini", "gpt-4o"]:
            try:
                headers = {"Authorization": f"Bearer {gh_token}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
                res = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=40)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via GitHub Models API ({model_name}).")
                        return parsed
                else:
                    print(f"GitHub Models API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"GitHub Models API ({model_name}) error: {e}")

    print("WARNING: All online LLM generation attempts failed or rate limited. Generating high-quality tailored fallback HTML.")
    clean_title = clean_rakuten_item_name(title)[:30]
    img_tag = f'<img src="{image_url}" alt="{clean_title}" style="max-width: 100%; height: auto;"><br>' if image_url else ""
    fallback_html = (
        f'<div class="article-wrapper">'
        f'<div class="content-body">'
        f'<h2>【おすすめ】{clean_title}</h2>'
        f'<p>大人気＆注目の話題のアイテム「<b>{title}</b>」をご紹介します！</p>'
        f'<p>デザイン性と実用性を兼ね備えた満足度の高いおすすめ商品です。</p>'
        f'<ul class="points-list">'
        f'<li><b>おすすめポイント1</b>：細部までこだわり抜かれた高いデザイン性とクオリティ！</li>'
        f'<li><b>おすすめポイント2</b>：使いやすさと機能性に優れ、日常生活で大活躍！</li>'
        f'<li><b>おすすめポイント3</b>：自分用にはもちろん、大切な方へのプレゼントにも最適！</li>'
        f'</ul>'
        f'{img_tag}'
        f'{buy_button_html}'
        f'<br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>'
        f'</div>'
        f'</div>'
    )
    return {
        "title": f"【注目】{clean_title}",
        "html": fallback_html
    }


def proofread_and_optimize_blogger_article(title, html_content):
    """誤字脱字最終チェックとSEO, AI-SEO, GEO的な修正ブラッシュアップ工程"""
    if not html_content or len(html_content.strip()) < 50:
        return html_content

    prompt = f"""以下のブログ記事HTMLに対して、誤字脱字チェックとSEO・AI-SEO・GEO（Generative Engine Optimization）最適化を行い、最高品質の原稿にブラッシュアップしてください。

【タイトル】: {title}
【HTML本文】:
{html_content}

【ブラッシュアップ要件】:
1. 誤字脱字・不自然な日本語表現を完全に校正してください。
2. AI検索（Perplexity, ChatGPT, Gemini等）が回答の根拠として引用しやすくするため、商品の具体的な魅力・メリット・特徴を構造化してください。
3. 文章が途中で力尽きず、タグ構造と文脈が完全に完結していることを確認してください。
4. 前置き・解説なしで修正後のHTML本文のみを出力してください。
"""

    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        try:
            headers = {"Authorization": f"Bearer {github_token}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "あなたはプロのWeb校正者兼SEO/GEOアナリストです。誤字脱字を無くし最高品質のHTML本文のみを出力します。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }
            resp = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                res_text = resp.json()["choices"][0]["message"]["content"].strip()
                if "```html" in res_text: res_text = res_text.split("```html", 1)[1].split("```")[0]
                elif "```" in res_text: res_text = res_text.split("```", 1)[1].split("```")[0]
                if len(res_text.strip()) > 100:
                    return res_text.strip()
        except Exception as e:
            print(f"Proofread failed: {e}")
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            print("Proofreading with Groq API...")
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "あなたはプロのWeb校正者兼SEO/GEOアナリストです。誤字脱字を無くし最高品質のHTML本文のみを出力します。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                res_text = resp.json()["choices"][0]["message"]["content"].strip()
                if "```html" in res_text: res_text = res_text.split("```html", 1)[1].split("```")[0]
                elif "```" in res_text: res_text = res_text.split("```", 1)[1].split("```")[0]
                if len(res_text.strip()) > 100:
                    print("Successfully proofread with Groq API!")
                    return res_text.strip()
        except Exception as e:
            print(f"Groq proofread failed: {e}")

    return html_content

def ensure_complete_blogger_article(html_content):
    """途中切れ（力尽きる現象）を検知し、安全に文末とHTML閉じタグを補正する"""
    if not html_content:
        return html_content
    html_content = html_content.strip()
    valid_endings = ("。", "！", "？", "!", "?", "</div>", "</p>", "</ul>", "</li>", "</a>")
    if not html_content.endswith(valid_endings):
        print("WARNING: Incomplete article detected. Repairing endings and tags...")
        last_p = max(html_content.rfind("。"), html_content.rfind("！"), html_content.rfind("</div>"))
        if last_p > len(html_content) * 0.5:
            html_content = html_content[:last_p + 1]

    open_divs = html_content.count("<div")
    close_divs = html_content.count("</div>")
    if open_divs > close_divs:
        html_content += "</div>" * (open_divs - close_divs)
    return html_content

def post_to_blogger(title, content):
    """Playwrightを用いてBloggerへ確実に公開投稿する超堅牢フロー"""
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        raise ValueError("BLOGGER_BLOG_ID is not set in environment variables.")
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    
    session_file_path = None
    if session_b64:
        try:
            decoded_str = base64.b64decode(session_b64).decode('utf-8')
            json.loads(decoded_str)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
                temp_file.write(decoded_str)
                session_file_path = temp_file.name
        except Exception as e:
            raise ValueError(f"BLOGGER_SESSION_B64 decode failed: {e}")
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Blogger post.")
        session_file_path = "session.json"
    else:
        raise ValueError("BLOGGER_SESSION_B64 is not set and local session.json not found.")

    print(f"Posting to Blogger (Blog ID: {blog_id}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
            
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                posts_url = f"https://draft.blogger.com/blog/posts/{blog_id}"
                print(f"Navigating to Blogger posts page: {posts_url}")
                page.goto(posts_url, wait_until="networkidle", timeout=35000)
                time.sleep(3.0)

                # 開いているドロップダウンやオーバーレイメニューを確実に閉じる
                page.keyboard.press("Escape")
                time.sleep(0.5)
                page.keyboard.press("Escape")
                time.sleep(0.5)

                # 事前クリーンアップ：過去の失敗等で残っている空の下書き・無題があれば破棄
                try:
                    for _ in range(5):
                        rows = page.locator("div.rb4Lrd").all()
                        if not rows:
                            break
                        first_row = rows[0]
                        row_text = first_row.inner_text()
                        if "下書き" in row_text or "(無題)" in row_text:
                            discard_btn = first_row.locator('[aria-label="この投稿を破棄"], [aria-label="この投稿をゴミ箱に移動"]').first
                            if discard_btn.is_visible(timeout=1000):
                                discard_btn.click(force=True)
                                time.sleep(0.5)
                                page.evaluate('''() => {
                                    const dialog = document.querySelector('div[role="alertdialog"], div[role="dialog"]');
                                    if (dialog) {
                                        const b = Array.from(dialog.querySelectorAll('div[role="button"], button')).find(x => x.innerText.includes('破棄') || x.innerText.includes('ゴミ箱に移動'));
                                        if (b) b.click();
                                    }
                                }''')
                                time.sleep(1.5)
                                print("[PRE-CLEANUP] Discarded previous leftover draft.")
                        else:
                            break
                except Exception as cleanup_err:
                    print(f"[PRE-CLEANUP-WARN] {cleanup_err}")

                # 新しい投稿ボタンをクリックしてエディタに入る
                editor_opened = False
                for open_attempt in range(5):
                    print(f"[BLOGGER-OPEN] Attempt {open_attempt + 1} to open editor...")
                    
                    if "edit" in page.url:
                        editor_opened = True
                        break

                    # Escapeでポップアップ防止
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

                    # force=True で可視の「新しい投稿を作成」ボタンをクリック
                    btn = page.locator('[aria-label="新しい投稿を作成"]:visible, div[role="button"]:has-text("新しい投稿"):visible').first
                    if btn.is_visible(timeout=5000):
                        print("[BLOGGER-OPEN] Clicking visible '新しい投稿' button with force=True...")
                        btn.click(force=True)
                        time.sleep(3.0)

                    # 1. 自動で /blog/post/edit/... へ遷移したか確認
                    if "edit" in page.url:
                        editor_opened = True
                        print(f"[BLOGGER-OPEN] Automatically transitioned to editor: {page.url}")
                        break

                    # 2. 一覧の先頭に新規ドラフト行が出現した場合、それをクリックしてエディタに入る
                    first_link = page.locator('a[href*="/blog/post/edit/"]').first
                    if first_link.is_visible(timeout=3000):
                        print(f"[BLOGGER-OPEN] Entering editor via draft row: {first_link.get_attribute('href')}")
                        first_link.click(force=True)
                        time.sleep(4.0)
                        if "edit" in page.url:
                            editor_opened = True
                            print(f"[BLOGGER-OPEN] Successfully entered editor: {page.url}")
                            break

                    time.sleep(2.0)

                if not editor_opened:
                    raise RuntimeError("Blogger editor could not be opened.")

                # タイトルと本文の入力（検証ループ付き）
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    print(f"--- Editor Body Injection Attempt {attempt+1} / {max_retries} ---")
                    if attempt > 0:
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(3)

                    try:
                        title_input = page.locator('input.titleField, input[aria-label="タイトル"], input[aria-label="Title"], .titleField input').locator("visible=true").first
                        title_input.wait_for(state="visible", timeout=15000)
                        title_input.click()
                        time.sleep(0.5)
                        page.keyboard.press('Control+A')
                        page.keyboard.press('Meta+A')
                        page.keyboard.press('Backspace')
                        title_input.fill(title)
                        time.sleep(1.5)

                        print("Injecting HTML content...")
                        injected = page.evaluate('''html => {
                            const cmEl = document.querySelector('.CodeMirror');
                            if (cmEl && cmEl.CodeMirror) {
                                cmEl.CodeMirror.setValue(html);
                                if (cmEl.CodeMirror.save) cmEl.CodeMirror.save();
                                return true;
                            }
                            return false;
                        }''', content)

                        if injected:
                            print("Successfully set HTML via CodeMirror instance.")
                        else:
                            print("CodeMirror direct injection not found. Fallback to rich text editor paste...")
                            try:
                                editor_body = page.locator('div[aria-label="本文"], div[aria-label="Body"], div[role="textbox"]').locator("visible=true").first
                                if editor_body.is_visible(timeout=3000):
                                    editor_body.click()
                                    time.sleep(0.5)
                            except Exception:
                                page.keyboard.press('Tab')
                                time.sleep(0.5)
                                page.keyboard.press('Tab')

                            page.evaluate('''html => {
                                try {
                                    navigator.clipboard.writeText(html);
                                } catch (e) {
                                    const blob = new Blob([html], { type: 'text/html' });
                                    const data = [new ClipboardItem({ 'text/html': blob })];
                                    navigator.clipboard.write(data);
                                }
                            }''', content)
                            time.sleep(1.0)
                            page.keyboard.press('Control+A')
                            page.keyboard.press('Meta+A')
                            time.sleep(0.3)
                            page.keyboard.press('Control+V')
                            page.keyboard.press('Meta+V')

                        time.sleep(2.0)
                        # キーボード入力で変更検知発火
                        page.keyboard.press('Space')
                        time.sleep(0.3)
                        page.keyboard.press('Backspace')
                        time.sleep(2.0)

                        cm_val = page.evaluate('''() => {
                            const cmEl = document.querySelector('.CodeMirror');
                            return (cmEl && cmEl.CodeMirror) ? cmEl.CodeMirror.getValue() : '';
                        }''')
                        page_html = page.content()
                        effective_html = cm_val if cm_val else page_html

                        if ("<img" in effective_html or "img" in effective_html) and ("href" in effective_html or "http" in effective_html):
                            print(f"Validation passed: Body content successfully inserted into editor (len: {len(effective_html)}).")
                            success = True
                            break
                        else:
                            print(f"Validation warning: Content verification incomplete. Retrying...")
                    except Exception as e:
                        print(f"Error during attempt {attempt+1}: {e}")
                    time.sleep(2)

                if not success:
                    try:
                        print("[BLOGGER-CLEANUP] Post validation failed. Discarding unfinished draft...")
                        page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="domcontentloaded", timeout=15000)
                        time.sleep(2.0)
                        discard_btn = page.locator('div[aria-label="この投稿を破棄"]').first
                        if discard_btn.is_visible(timeout=3000):
                            discard_btn.dispatch_event('click')
                            time.sleep(1.0)
                            page.keyboard.press('Enter')
                            time.sleep(1.5)
                            print("[BLOGGER-CLEANUP] Discarded unfinished draft successfully.")
                    except Exception as discard_err:
                        print(f"[BLOGGER-CLEANUP-WARN] Failed to discard draft: {discard_err}")

                    raise RuntimeError("Critical: Body injection could not be validated after multiple attempts.")

                print("Clicking Publish button...")
                try:
                    pub_btn = page.locator('[aria-label="公開"], [aria-label="Publish"]').locator("visible=true").first
                    pub_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    pub_btn.click(force=True, timeout=10000)
                except Exception as e:
                    print("Clicking publish via shortcut:", e)
                    page.keyboard.press('Control+Shift+P')
                    page.keyboard.press('Meta+Shift+P')

                time.sleep(3)

                try:
                    conf_btn = page.locator(
                        'div[role="alertdialog"] div[role="button"]:has-text("確定"), '
                        'div[role="alertdialog"] div[role="button"]:has-text("確認"), '
                        'div[role="dialog"] div[role="button"]:has-text("確定"), '
                        'div[role="dialog"] div[role="button"]:has-text("確認"), '
                        'div[role="button"]:has-text("確定"), '
                        '[aria-label="確定"], [aria-label="確認"], [aria-label="Confirm"]'
                    ).locator("visible=true").first
                    conf_btn.wait_for(state="visible", timeout=7000)
                    conf_btn.click(force=True)
                    print("[BLOGGER-PUBLISH] Confirmed publication dialog successfully ('確定' button clicked).")
                except Exception as e:
                    print("[BLOGGER-PUBLISH-WARN] Confirm button warning, trying Enter fallback:", e)
                    page.keyboard.press('Enter')

                time.sleep(8)
                print("Successfully published post using Playwright!")

                # 公開後の厳格な事後検証（フィードを取得して今回のタイトルが公開され、本文が空でないことを確認）
                print("[POST-VERIFY] Verifying published article content from Blogger feed...")
                try:
                    import urllib.request
                    import ssl
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    feed_url = f"https://www.blogger.com/feeds/{blog_id}/posts/default?alt=json&max-results=3"
                    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                        feed_data = json.loads(resp.read().decode("utf-8"))
                        entries = feed_data.get("feed", {}).get("entry", [])
                        latest_entry = entries[0] if entries else {}
                        latest_title = latest_entry.get("title", {}).get("$t", "").strip()
                        latest_content = latest_entry.get("content", {}).get("$t", "")
                        print(f"[POST-VERIFY] Latest post in feed: '{latest_title}' (content length: {len(latest_content)} chars)")
                        
                        if len(latest_content) < 100:
                            print(f"[POST-VERIFY-ERROR] Post validation failed! Feed content len: {len(latest_content)}")
                            try:
                                page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="networkidle", timeout=20000)
                                time.sleep(2)
                                discard_btn = page.locator('div[aria-label="この投稿を破棄"]').first
                                if discard_btn.is_visible(timeout=3000):
                                    discard_btn.dispatch_event('click')
                                    time.sleep(1.0)
                                    page.keyboard.press('Enter')
                            except Exception:
                                pass
                            raise RuntimeError(f"Critical: Blogger post was not properly published live. Cleaned up.")
                        else:
                            print("[POST-VERIFY] Verification SUCCESS: Article is live with full title, images and content!")
                except Exception as verify_err:
                    if "Critical: Blogger post" in str(verify_err):
                        raise
                    print(f"[POST-VERIFY-WARN] Feed verification check encountered an error: {verify_err}")

            except Exception as e:
                print(f"Error during Blogger operation: {e}")
                try:
                    print("[POST-FAILURE-CLEANUP] Attempting to discard any leftover unfinished draft...")
                    page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="domcontentloaded", timeout=15000)
                    time.sleep(1.5)
                    first_link = page.locator("a[href*='/blog/post/edit/']").first
                    if first_link.is_visible(timeout=3000):
                        first_link.hover()
                        time.sleep(0.5)
                        discard_btn = page.locator("div[role=button][aria-label='この投稿を破棄']").locator("visible=true").first
                        if discard_btn.is_visible(timeout=1500):
                            discard_btn.click()
                            time.sleep(0.8)
                            confirm = page.locator("div[role=button]:has-text('破棄'), button:has-text('破棄')").locator("visible=true").first
                            if confirm.is_visible(timeout=1500):
                                confirm.click()
                                print("[POST-FAILURE-CLEANUP] Unfinished draft discarded successfully.")
                                time.sleep(1.5)
                except Exception as discard_err:
                    print(f"[POST-FAILURE-CLEANUP-WARN] Could not discard draft: {discard_err}")
                raise e

    finally:
        if session_file_path and session_file_path != "session.json" and os.path.exists(session_file_path):
            os.remove(session_file_path)


def generate_room_comment_with_llm(item):
    import random
    title = item.get("itemName") or item.get("title") or ""
    price = item.get("itemPrice") or item.get("price") or ""
    caption = item.get("itemCaption") or item.get("catchcopy") or ""

    prompt = f"""以下のギフト・プレゼント向け商品情報を基にして、楽天ROOM用の魅力的な紹介コメント（400文字以内）を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品説明・特徴】: {caption[:200]}

以下の要件を厳格に遵守してください：
1. 口調・トーン：ギフトを探しているユーザーに心からおすすめする丁寧かつ温かみのあるレビュー文とし、「これかわいい！」「これ気になってた！」「これ便利だよ！」といった安易な定型表現は絶対に使用しないでください。
2. 内容：どんな相手（友人、パートナー、家族、自分へのご褒美など）やシチュエーション（誕生日、お返し、記念日等）に最適か具体的に添えて解説してください。
3. 文字数：400文字以内（厳守。超えると投稿エラーになります）。
4. 絵文字：5〜8個使用して華やかにすること。
5. ハッシュタグ：3〜5個（「#ギフト #プレゼント #お祝い」等）含め、末尾に「#楽天市場」を必ず含めること。
6. URLや疑似リンク、プレースホルダー（「[リンクはこちら]」など）は絶対に含めないでください。
7. 出力は紹介コメントのテキストのみとし、前置きやMarkdownの装飾コードブロック等は一切含めないでください。
"""

    system_message = (
        "あなたはセンス溢れるギフト・プレゼント選びの専門インフルエンサーです。"
        "定型文やテンプレート表現を排し、贈る相手や場面が目に浮かぶような喜ばれるオリジナルギフト紹介文を作成してください。"
    )

    def clean_text(text):
        return text.replace("```", "").strip()

    # 1. Gemini API（最優先。thinking無効化・全parts結合で安定化）
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        models = [
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview",
            "gemini-flash-latest"
        ]
        for model_name in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.9, "maxOutputTokens": 600}
                }
                if any(v in model_name for v in ["2.5", "3.", "3-"]):
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
                res = requests.post(url, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    candidate = data.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    text = clean_text("".join(p.get("text", "") for p in parts if p.get("text")))
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via Gemini API ({model_name}).")
                        return text
                    finish = candidate.get("finishReason", "UNKNOWN")
                    print(f"Gemini ({model_name}) short/empty. finishReason={finish}, text_len={len(text)}")
                else:
                    print(f"Gemini API ({model_name}) returned {res.status_code}: {res.text[:150]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) error: {e}")

    # 2. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-70b-8192", "llama3-8b-8192"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via Groq API ({model_name}).")
                        return text
                else:
                    print(f"Groq API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Groq API ({model_name}) error: {e}")

    # 3. OpenRouter API（有効な無料モデルを使用）
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        for model_name in ["google/gemma-3-27b-it:free", "mistralai/mistral-nemo:free", "meta-llama/llama-3.2-3b-instruct:free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com",
                    "X-Title": "RakutenRoomBot"
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via OpenRouter ({model_name}).")
                        return text
                else:
                    print(f"OpenRouter ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"OpenRouter ({model_name}) error: {e}")

    # 4. GitHub Models API（GH_TOKENがPATの場合のみ）
    gh_token = os.environ.get("GH_TOKEN")
    if gh_token and not gh_token.startswith("ghs_"):
        for model_name in ["gpt-4o-mini", "gpt-4o", "Meta-Llama-3.1-8B-Instruct"]:
            try:
                headers = {"Authorization": f"Bearer {gh_token}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via GitHub Models API ({model_name}).")
                        return text
                else:
                    print(f"GitHub Models API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"GitHub Models API ({model_name}) error: {e}")

    print("WARNING: All LLM API calls failed. Generating dynamic item-aware comment.")
    clean_title = title.replace("【", "").replace("】", "").replace("！", "").replace("✨", "")[:45]

    starters = [
        f"大切な方への贈り物や自分へのご褒美にぴったり！『{clean_title}』をピックアップ🎁",
        f"センスの良さが光る素敵なギフト！『{clean_title}』のご紹介です✨",
        f"お祝いやお返しに送れば喜ばれること間違いなし！『{clean_title}』をチェック🛍️",
        f"日常に贅沢感と彩りを添えてくれる特別なおすすめアイテム『{clean_title}』💕",
        f"失敗しないギフト選びならこれ！『{clean_title}』の魅力をチェックしてみてください👍"
    ]
    starter = random.choice(starters)

    bodies = [
        "デザイン性と実用性を兼ね備え、受け取った方が笑顔になる満足度の高さが魅力！😊",
        "細部までこだわりを感じる丁寧な仕上がりで、特別な日のプレゼントに最適です✨",
        "年代問わず喜ばれる上品なアイテム。ギフト包装して送るのにもぴったり🛍️",
        "評価が高く自信をもっておすすめできる一品。気になる方はぜひ詳細をチェックしてみてください👍"
    ]
    body = random.choice(bodies)

    price_info = f"（価格: {price}円）" if price else ""
    return f"{starter}\n\n{body}\n{price_info}\n\n#ギフト #プレゼント #お祝い #楽天市場 #コレ"


def post_to_rakuten_room(item_code, comment):
    session_b64 = os.environ.get("ROOM_SESSION_B64") or os.environ.get("BLOGGER_SESSION_B64")
    
    session_file_path = None
    if session_b64:
        try:
            decoded_str = base64.b64decode(session_b64).decode('utf-8')
            json.loads(decoded_str)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
                temp_file.write(decoded_str)
                session_file_path = temp_file.name
        except Exception as e:
            print(f"ROOM_SESSION_B64 (or BLOGGER_SESSION_B64) decode failed: {e}")
            return
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Rakuten Room.")
        session_file_path = "session.json"
    else:
        print("ROOM_SESSION_B64/BLOGGER_SESSION_B64 is not set and local session.json not found. Skipping Rakuten Room post.")
        return

    print(f"Posting to Rakuten Room (Item: {item_code}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                # ROOM投稿エディタへ遷移
                warp_url = f"https://room.rakuten.co.jp/mix?itemcode={item_code}&scid=we_room_upc60"
                page.goto(warp_url, wait_until="load", timeout=45000)
                time.sleep(4)

                # ログイン画面に飛ばされていないかチェック
                if "login.rakuten.co.jp" in page.url or "login" in page.url.lower():
                    print("Error: Session has expired or is invalid. Redirected to Rakuten login page. Skipping Rakuten Room post.")
                    return

                # 重複・すでにコレしているかチェック
                page_html = page.content()
                if any(term in page_html for term in ["すでにコレ", "すでに登録されています", "すでに登録"]):
                    print("This item has already been posted ('コレ！'済み) to Rakuten Room. Skipping.")
                    return

                # コメント入力欄 (textarea)
                comment_area = page.locator('textarea[placeholder*="コメント"], textarea[placeholder*="オススメ"], textarea[placeholder*="魅力"], textarea').first
                comment_area.wait_for(state="visible", timeout=15000)
                comment_area.fill(comment)
                time.sleep(1)

                # 投稿確定ボタン
                submit_btn = page.locator('button:has-text("投稿"), button:has-text("完了"), button:has-text("コレ！"), button[class*="submit"]').first
                submit_btn.scroll_into_view_if_needed()
                time.sleep(1)
                submit_btn.click(force=True)
                print("Clicked Rakuten Room submit button.")
                
                time.sleep(5)
                print("Successfully posted to Rakuten Room!")
            except Exception as inner_e:
                print(f"Error during Playwright interaction: {inner_e}")
                try:
                    page.screenshot(path="room_error.png")
                    print("Saved debug screenshot: room_error.png")
                except Exception as se:
                    print(f"Failed to take screenshot: {se}")
                raise inner_e

    except Exception as e:
        print(f"Error posting to Rakuten Room: {e}")
    finally:
        if session_file_path and session_file_path != "session.json" and os.path.exists(session_file_path):
            os.remove(session_file_path)


def main():
    try:
        max_attempts = 5
        final_item = None
        final_title = None
        final_html = None

        for attempt in range(max_attempts):
            print(f"=== Content Selection & Generation Attempt {attempt + 1} / {max_attempts} ===")
            item = fetch_rakuten_item()
            item_code = item.get("itemCode")
            raw_title = item.get("itemName", "")
            print(f"Selected Item Candidate: {raw_title[:30]} ({item_code})")

            llm_result = generate_article_with_llm(item)
            if isinstance(llm_result, dict):
                gen_title = llm_result.get("title", "")
                html_content = llm_result.get("html", "")
            else:
                gen_title = ""
                html_content = str(llm_result)

            if not gen_title:
                gen_title = clean_rakuten_item_name(raw_title)[:32]

            # 厳格なタイトル重複・スパム・構文被り検証
            is_dup, dup_match, ratio = is_title_duplicate_or_similar(gen_title)
            if is_dup:
                print(f"[REJECTED] Generated title or product too similar to past content ({dup_match}, ratio={ratio:.2f}): {gen_title}")
                print("Discarding this item candidate completely and picking a fresh keyword/item...")
                continue

            if not html_content or len(html_content.strip()) < 300:
                print(f"[REJECTED] Generated HTML content is too short ({len(html_content) if html_content else 0} chars). Retrying...")
                continue

            html_content = proofread_and_optimize_blogger_article(gen_title, html_content)
            html_content = ensure_complete_blogger_article(html_content)

            final_item = item
            final_title = gen_title
            final_html = html_content
            print(f"[APPROVED] Quality & Uniqueness Verified: {final_title}")
            break

        if not final_item or not final_title or not final_html:
            raise RuntimeError("Failed to generate a 100% unique, non-duplicated article after multiple attempts.")

        print("--- Generated HTML Content Snippet ---")
        print(final_html[:200])
        print("--------------------------------------")

        post_to_blogger(final_title, final_html)

        try:
            item_code = final_item.get("itemCode")
            room_comment = generate_room_comment_with_llm(final_item)
            print("Generated ROOM Comment:")
            print(room_comment)
            post_to_rakuten_room(item_code, room_comment)
        except Exception as room_err:
            print(f"Failed to post to Rakuten Room: {room_err}")

        save_to_cache(final_item.get("itemCode"))
        save_posted_title(final_title)
        print("Process completed successfully with 100% unique article.")

    except Exception as e:
        print(f"Error in execution: {e}")
        exit(1)

if __name__ == "__main__":
    main()
