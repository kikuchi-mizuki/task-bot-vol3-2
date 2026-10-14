import openai
from datetime import datetime, timedelta
from dateutil import parser
import re
import json
from config import Config
import calendar
import pytz
import logging

logger = logging.getLogger("ai_service")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class AIService:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
    
    def _get_jst_now_str(self):
        now = datetime.now(pytz.timezone('Asia/Tokyo'))
        return now.strftime('%Y-%m-%dT%H:%M:%S%z')
    
    def extract_dates_and_times(self, text):
        """テキストから日時を抽出し、タスクの種類を判定します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "【最重要】ユーザーの入力が箇条書き・改行・スペース・句読点で区切られている場合も、全ての時間帯・枠を必ず個別に抽出してください。\n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "あなたは日時抽出とタスク管理の専門家です。ユーザーのテキストを分析して、以下のJSON形式で返してください。\n\n"
                "分析ルール:\n"
                "1. 複数の日時がある場合は全て抽出\n"
                "2. 日本語の日付表現（今日、明日、来週月曜日など）を具体的な日付に変換\n"
                "3. **「来週」という表現は必ず1週間分（7日間）の日付として抽出してください**\n"
                "   - 例：「来週」→ 来週月曜日から日曜日までの7日間\n"
                "   - 例：「来週の空き時間」→ 来週月曜日〜日曜日の7日間の空き時間\n"
                "3-1. **日付範囲（例：12/5-12/28、12/5〜12/28）は必ず個別の日付に展開してください**\n"
                "   - 例：「12/5-12/28」→ 12/5、12/6、12/7、...、12/28の各日付を個別に抽出\n"
                "   - 例：「12/5-12/28の空き時間」→ 12/5から12/28までの全ての日付の空き時間を確認\n"
                "   - 日付範囲が指定されている場合は、開始日から終了日までの全ての日付をdates配列に含めてください\n"
                "4. 月が指定されていない場合（例：16日、17日）は今月として認識\n"
                "4-1. **月だけが指定された場合の年の判定（最重要）**\n"
                "   - 現在の月よりも前の月が指定された場合は、来年として認識してください\n"
                "   - 例：現在が2025年12月の場合、「1月」と指定されたら2026年1月として認識\n"
                "   - 例：現在が2025年12月の場合、「12月」と指定されたら2025年12月として認識\n"
                "   - 例：現在が2025年1月の場合、「12月」と指定されたら2025年12月として認識（まだ先の月）\n"
                "   - 例：現在が2025年1月の場合、「1月」と指定されたら2025年1月として認識\n"
                "5. 時間表現（午前9時、14時30分、9-10時、9時-10時、9:00-10:00など）を24時間形式に変換\n"
                "6. **タスクの種類を判定（最重要）**:\n   - availability_check: 空き時間を確認したい（「〇日空いてる？」「空き時間教えて」「〇日〜〇日の空き時間」）\n   - add_event: 予定を追加したい（日時＋タイトルがある）\n   - get_events: 既存の予定を見たい（「今日の予定は？」「来週のスケジュール」「〇日は何がある？」「忙しい？」）\n   - suggest_time: 予定を入れたいが日時が決まっていない（「来週会食を入れたい」「今週中に打ち合わせしたい」「〇〇したい」）\n   - unknown: カレンダーと無関係な質問\n   - 日時のみ（タイトルや内容がない）場合は必ず「availability_check」（空き時間確認）\n   - 日時+タイトル/予定内容がある場合は「add_event」（予定追加）\n   - 例：「7/8 18時以降」→ availability_check（日時のみ）\n   - 例：「7/10 18:00〜20:00」→ availability_check（日時のみ）\n   - 例：「・7/10 9-10時\n・7/11 9-10時」→ availability_check（日時のみ複数）\n   - 例：「7/10 9-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9時-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9:00-10:00」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7月18日 11:00-14:00,15:00-17:00」→ availability_check（日時のみ複数）\n   - 例：「7月20日 13:00-0:00」→ availability_check（日時のみ）\n   - 例：「明日の午前9時から会議を追加して」→ add_event（日時+予定内容）\n   - 例：「来週月曜日の14時から打ち合わせ」→ add_event（日時+予定内容）\n   - 例：「田中さんとMTG」→ add_event（予定内容あり）\n   - 例：「会議を追加」→ add_event（予定内容あり）\n   - 例：「今日の予定は？」→ get_events（既存予定確認）\n   - 例：「来週忙しい？」→ get_events（既存予定確認）\n   - 例：「週末空いてる？」→ availability_check（空き時間確認）\n   - 例：「来週会食を入れたい」→ suggest_time（予定提案）\n   - 例：「今週中に打ち合わせしたい」→ suggest_time（予定提案）\n   - 例：「天気は？」→ unknown（カレンダー無関係）\n"
                "7. 自然言語の時間表現は必ず具体的な時刻範囲・日付範囲に変換してください。\n"
                "   例：'18時以降'→'18:00〜23:59'、'終日'→'00:00〜23:59'、'今日'→'現在時刻〜23:59'、'今日から1週間'→'今日〜7日後の23:59'。\n"
                "   終了時間が指定されていない場合は1時間の予定として認識してください（例：'10時'→'10:00〜11:00'）。\n"
                "8. 箇条書き（・や-）、改行、スペース、句読点で区切られている場合も、すべての日時・時間帯を抽出してください。\n"
                "   例：'・7/10 9-10時\n・7/11 9-10時' → 2件の予定として抽出\n"
                "   例：'7/11 15:00〜16:00 18:00〜19:00' → 2件の予定として抽出\n"
                "   例：'7/12 終日' → 1件の終日予定として抽出\n"
                "9. 同じ日付の終日予定は1件だけ抽出してください。\n"
                "10. 予定タイトル（description）も必ず抽出してください。\n"
                "11. \"終日\"や\"00:00〜23:59\"の終日枠は、ユーザーが明示的に\"終日\"と書いた場合のみ抽出してください。\n"
                "12. 1つの日付に複数の時間帯（枠）が指定されている場合は、必ずその枠ごとに抽出してください。\n"
                "13. 同じ日に部分枠（例: 15:00〜16:00, 18:00〜19:00）がある場合は、その日付の終日枠（00:00〜23:59）は抽出しないでください。\n"
                "14. 複数の日時・時間帯が入力される場合、全ての時間帯をリストにし、それぞれに対して開始時刻・終了時刻をISO形式（例: 2025-07-11T15:00:00+09:00）で出力してください。\n"
                "15. 予定タイトル（会議名や打合せ名など）と、説明（議題や詳細、目的など）があれば両方抽出してください。\n"
                "16. 説明はタイトル以降の文や\"の件\"\"について\"などを優先して抽出してください。\n"
                "17. **日時のみの入力の場合は必ずavailability_checkとして判定してください。予定の内容や目的が明確に示されていない場合は空き時間確認として扱ってください。**\n"
                "18. **場所情報（例：東京、大阪など）が入力されている場合は、locationフィールドに抽出してください。**\n"
                "    - 例：「来月の東京での空き時間を教えて」→ location: '東京'\n"
                "    - 例：「11月の大阪の空き時間」→ location: '大阪'\n"
                "19. **移動時間（例：移動時間は1時間、移動に1時間かかる）が入力されている場合は、travel_time_minutesフィールドに抽出してください。**\n"
                "    - 例：「11月の空き時間を教えて。移動時間は1時間。」→ travel_time_minutes: 60\n"
                "    - 例：「移動時間30分かかります」→ travel_time_minutes: 30\n"
                "20. **希望する枠の最低長さが指定されている場合（例：「2時間」「90分以上」など）は、required_duration_minutesとして抽出してください。**\n"
                "    - 例：「2時間の空き時間」→ required_duration_minutes: 120\n"
                "    - 例：「90分の打ち合わせができる時間」→ required_duration_minutes: 90\n"
                "\n"
                "【出力例】\n"
                "空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-08\",\n      \"time\": \"18:00\",\n      \"end_time\": \"23:59\"\n    }\n  ]\n}\n"
                "\n"
                "移動時間指定の空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"travel_time_minutes\": 60,\n  \"dates\": [\n    {\n      \"date\": \"2025-07-08\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    }\n  ]\n}\n"
                "\n"
                "来週の空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"dates\": [\n    {\n      \"date\": \"2025-01-20\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-21\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-22\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-23\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-24\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-25\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    },\n    {\n      \"date\": \"2025-01-26\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    }\n  ]\n}\n"
                "\n"
                "場所指定の空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"location\": \"東京\",\n  \"dates\": [\n    {\n      \"date\": \"2025-01-20\",\n      \"time\": \"08:00\",\n      \"end_time\": \"22:00\"\n    }\n  ]\n}\n"
                "\n"
                "予定追加の場合:\n"
                "{\n  \"task_type\": \"add_event\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-14\",\n      \"time\": \"20:00\",\n      \"end_time\": \"21:00\",\n      \"title\": \"田中さんMTG\",\n      \"description\": \"新作アプリの件\"\n    }\n  ]\n}\n"
                "\n"
                "既存予定確認の場合（get_events）:\n"
                "{\n  \"task_type\": \"get_events\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-14\",\n      \"time\": \"00:00\",\n      \"end_time\": \"23:59\"\n    }\n  ]\n}\n"
                "\n"
                "予定提案の場合（suggest_time）:\n"
                "{\n  \"task_type\": \"suggest_time\",\n  \"title\": \"会食\",\n  \"dates\": [\n    {\n      \"date\": \"2025-01-20\",\n      \"time\": \"00:00\",\n      \"end_time\": \"23:59\"\n    },\n    {\n      \"date\": \"2025-01-21\",\n      \"time\": \"00:00\",\n      \"end_time\": \"23:59\"\n    }\n  ]\n}\n"
                "\n"
                "カレンダー無関係の場合（unknown）:\n"
                "{\n  \"task_type\": \"unknown\"\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1
            )
            result = response.choices[0].message.content
            logger.info(f"[DEBUG] AI生レスポンス: {result}")
            parsed = self._parse_ai_response(result)
            
            # AIの判定結果を強制的に修正
            if parsed and isinstance(parsed, dict) and 'dates' in parsed:
                task_type_ai = parsed.get('task_type', '')
                # get_events / suggest_time / unknown はそのまま維持
                if task_type_ai not in ('get_events', 'suggest_time', 'unknown'):
                    # 日時のみの場合は強制的にavailability_checkに変更
                    has_title_or_description = False
                    for date_info in parsed.get('dates', []):
                        if date_info.get('title') or date_info.get('description'):
                            has_title_or_description = True
                            break

                    if not has_title_or_description:
                        logger.info(f"[DEBUG] 日時のみのため、task_typeをavailability_checkに強制変更")
                        parsed['task_type'] = 'availability_check'
            
            return self._supplement_times(parsed, text)
            
        except Exception as e:
            return {"error": "イベント情報を正しく認識できませんでした。\n\n・日時を打つと空き時間を返します\n・予定を打つとカレンダーに追加します\n\n例：\n『明日の午前9時から会議を追加して』\n『来週月曜日の14時から打ち合わせ』"}
    
    def _parse_ai_response(self, response):
        """AIの応答をパースします"""
        try:
            # JSON部分を抽出
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {"error": "AI応答のパースに失敗しました"}
        except Exception as e:
            return {"error": f"JSONパースエラー: {str(e)}"}
    
    def _supplement_times(self, parsed, original_text):
        from datetime import datetime, timedelta
        import re
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        logger = logging.getLogger("ai_service")
        print(f"[DEBUG] _supplement_times開始: parsed={parsed}")
        print(f"[DEBUG] 元テキスト: {original_text}")
        if not parsed or 'dates' not in parsed:
            print(f"[DEBUG] datesが存在しない: {parsed}")
            return parsed
        
        # 希望する枠の最低長さ（例: 2時間、90分）を抽出（移動時間ではないもの）
        required_duration_minutes = parsed.get('required_duration_minutes')
        if required_duration_minutes is None:
            # 「移動時間」を含まない時間指定のみを対象にする
            hours_match = re.search(r'(?<!移動)(\d+(?:\.\d+)?)\s*時間', original_text)
            minutes_match = re.search(r'(?<!移動)(\d+)\s*分', original_text)
            duration_total = 0
            if hours_match:
                try:
                    duration_total += int(float(hours_match.group(1)) * 60)
                except Exception:
                    pass
            if minutes_match:
                try:
                    duration_total += int(minutes_match.group(1))
                except Exception:
                    pass
            if duration_total > 0:
                required_duration_minutes = duration_total
                print(f"[DEBUG] 希望枠の長さを抽出: {required_duration_minutes}分")
        if required_duration_minutes is not None:
            parsed['required_duration_minutes'] = required_duration_minutes
        
        # 日付範囲を展開する処理（AIが展開できていない場合に備えて）
        # 例：12/5-12/28 → 12/5から12/28までの全ての日付
        # パターン1: 12/5-12/28 または 12/5〜12/28
        date_range_pattern1 = r'(\d{1,2})/(\d{1,2})[\-〜~](\d{1,2})/(\d{1,2})'
        # パターン2: 12月5日-12月28日 または 12月5日〜12月28日
        date_range_pattern2 = r'(\d{1,2})月(\d{1,2})日[\-〜~](\d{1,2})月(\d{1,2})日'
        
        date_range_match = re.search(date_range_pattern1, original_text) or re.search(date_range_pattern2, original_text)
        if date_range_match:
            groups = date_range_match.groups()
            if len(groups) == 4:
                start_month, start_day, end_month, end_day = groups
                start_month, start_day, end_month, end_day = int(start_month), int(start_day), int(end_month), int(end_day)
                year = now.year
                
                try:
                    # 開始日と終了日を計算
                    start_date = datetime(year, start_month, start_day)
                    end_date = datetime(year, end_month, end_day)
                    
                    # 開始日が過去の場合は来年として扱う
                    if start_date < now:
                        start_date = datetime(year + 1, start_month, start_day)
                        end_date = datetime(year + 1, end_month, end_day)
                    
                    # 終了日が開始日より前の場合は、終了日を来年として扱う（月を跨ぐ場合）
                    if end_date < start_date:
                        end_date = datetime(year + 1, end_month, end_day)
                    
                    # 日付範囲を展開
                    expanded_dates = []
                    current_date = start_date
                    while current_date <= end_date:
                        date_str = current_date.strftime('%Y-%m-%d')
                        # 既存のdatesに同じ日付がないかチェック
                        if not any(d.get('date') == date_str for d in parsed['dates']):
                            # 時間が指定されていない場合はデフォルト値を設定
                            time = '08:00'
                            end_time = '22:00'
                            # 既存のdatesから時間を取得（最初のエントリから）
                            if parsed['dates']:
                                first_date = parsed['dates'][0]
                                if first_date.get('time'):
                                    time = first_date.get('time')
                                if first_date.get('end_time'):
                                    end_time = first_date.get('end_time')
                            
                            expanded_dates.append({
                                'date': date_str,
                                'time': time,
                                'end_time': end_time
                            })
                            print(f"[DEBUG] 日付範囲から展開: {date_str}")
                        current_date += timedelta(days=1)
                    
                    # 展開した日付をparsed['dates']に追加
                    if expanded_dates:
                        print(f"[DEBUG] 日付範囲展開: {len(expanded_dates)}日分を追加")
                        parsed['dates'].extend(expanded_dates)
                except Exception as e:
                    print(f"[DEBUG] 日付範囲展開エラー: {e}")
                    import traceback
                    traceback.print_exc()

        # 月だけが指定された場合の年の判定
        # 例：12月に「1月の空き時間」と聞かれた場合、2026年1月として扱う
        for d in parsed.get('dates', []):
            if 'date' in d:
                date_str = d['date']
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                    # 日付が過去の場合（年が正しく設定されていない可能性）
                    # 月が現在の月よりも前の場合は、来年として扱う
                    if dt.month < now.month and dt.year == now.year:
                        dt = datetime(now.year + 1, dt.month, dt.day)
                        d['date'] = dt.strftime('%Y-%m-%d')
                        print(f"[DEBUG] 月だけ指定のため来年に修正: {date_str} -> {d['date']}")
                except Exception as e:
                    print(f"[DEBUG] 月だけ指定の年判定エラー: {e}")

        allday_dates = set()
        new_dates = []
        # 1. AI抽出を最優先。time, end_timeが空欄のものだけ補完
        for d in parsed['dates']:
            print(f"[DEBUG] datesループ: {d}")
            phrase = d.get('description', '') or original_text
            # time, end_timeが両方セットされていれば何もしない
            if d.get('time') and d.get('end_time'):
                new_dates.append(d)
                continue
            # time, end_timeが空欄の場合のみ補完
            # 範囲表現
            range_match = re.search(r'(\d{1,2})[\-〜~](\d{1,2})時', phrase)
            if range_match:
                d['time'] = f"{int(range_match.group(1)):02d}:00"
                d['end_time'] = f"{int(range_match.group(2)):02d}:00"
            # 18時以降
            if (not d.get('time') or not d.get('end_time')) and re.search(r'(\d{1,2})時以降', phrase):
                m = re.search(r'(\d{1,2})時以降', phrase)
                if m:
                    d['time'] = f"{int(m.group(1)):02d}:00"
                    d['end_time'] = '23:59'
            # 終日
            if (not d.get('time') and not d.get('end_time')) or re.search(r'終日', phrase):
                d['time'] = '00:00'
                d['end_time'] = '23:59'
                if d.get('date') in allday_dates:
                    print(f"[DEBUG] 同じ日付の終日予定はスキップ: {d.get('date')}")
                    continue
                allday_dates.add(d.get('date'))
            # 明日
            if re.search(r'明日', phrase):
                d['date'] = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = '08:00'
                if not d.get('end_time'):
                    d['end_time'] = '22:00'
            # 今日
            if re.search(r'今日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                # 今日X時の形式を処理
                time_match = re.search(r'今日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                elif not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                # 今日の場合は終了時間を1時間後に強制設定（AIの設定を上書き）
                if d.get('time'):
                    from datetime import datetime, timedelta
                    time_obj = datetime.strptime(d.get('time'), "%H:%M")
                    end_time_obj = time_obj + timedelta(hours=1)
                    d['end_time'] = end_time_obj.strftime('%H:%M')
                    print(f"[DEBUG] 今日の終了時間を1時間後に強制設定: {d.get('time')} -> {d['end_time']}")
            # 本日
            if re.search(r'本日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                # 本日X時の形式を処理
                time_match = re.search(r'本日(\d{1,2})時', phrase)
                if time_match:
                    hour = int(time_match.group(1))
                    d['time'] = f"{hour:02d}:00"
                    d['end_time'] = f"{hour+1:02d}:00"
                    print(f"[DEBUG] 本日X時の処理: {hour}時 -> {hour+1}時")
                elif not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                # 本日の場合は終了時間を1時間後に強制設定（AIの設定を上書き）
                if d.get('time'):
                    from datetime import datetime, timedelta
                    time_obj = datetime.strptime(d.get('time'), "%H:%M")
                    end_time_obj = time_obj + timedelta(hours=1)
                    d['end_time'] = end_time_obj.strftime('%H:%M')
                    print(f"[DEBUG] 本日の終了時間を1時間後に強制設定: {d.get('time')} -> {d['end_time']}")
            # 来週
            if re.search(r'来週', phrase):
                # 来週の月曜日を計算
                # 月曜日(0)の場合: 来週の月曜日は7日後
                # 火曜日(1)の場合: 来週の月曜日は6日後
                # 水曜日(2)の場合: 来週の月曜日は5日後
                # 木曜日(3)の場合: 来週の月曜日は4日後
                # 金曜日(4)の場合: 来週の月曜日は3日後
                # 土曜日(5)の場合: 来週の月曜日は2日後
                # 日曜日(6)の場合: 来週の月曜日は1日後
                current_weekday = now.weekday()
                if current_weekday == 0:  # 月曜日の場合
                    days_until_next_monday = 7
                else:
                    days_until_next_monday = (7 - current_weekday) % 7
                    if days_until_next_monday == 0:
                        days_until_next_monday = 7
                next_monday = now + timedelta(days=days_until_next_monday)
                
                # 来週の7日間を生成
                week_dates = []
                for i in range(7):
                    week_date = next_monday + timedelta(days=i)
                    week_dates.append(week_date.strftime('%Y-%m-%d'))
                
                # 来週の各日付に対して空き時間確認のエントリを作成
                for week_date in week_dates:
                    week_entry = {
                        'date': week_date,
                        'time': '08:00',
                        'end_time': '22:00'
                    }
                    if not any(existing.get('date') == week_date for existing in new_dates):
                        new_dates.append(week_entry)
                        print(f"[DEBUG] 来週の日付を追加: {week_date}")
                
                # 元のエントリは削除（来週の処理で置き換え）
                continue
            # 今日から1週間
            if re.search(r'今日から1週間', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                d['end_date'] = (now + timedelta(days=6)).strftime('%Y-%m-%d')
                d['time'] = '00:00'
                d['end_time'] = '23:59'
            # end_timeが空
            if d.get('time') and not d.get('end_time'):
                # 終了時間が設定されていない場合は1時間後に設定
                from datetime import datetime, timedelta
                time_obj = datetime.strptime(d.get('time'), "%H:%M")
                end_time_obj = time_obj + timedelta(hours=1)
                d['end_time'] = end_time_obj.strftime('%H:%M')
            # title補完
            if not d.get('title') or d['title'] == '':
                if d.get('description'):
                    d['title'] = d['description']
                elif parsed.get('task_type') == 'add_event':
                    t = d.get('time', '')
                    e = d.get('end_time', '')
                    d['title'] = f"予定（{d.get('date', '')} {t}〜{e}）"
            new_dates.append(d)
        print(f"[DEBUG] new_dates(AI+補完): {new_dates}")
        # 2. 正規表現で漏れた枠を「追加」する（AI抽出に無い場合のみ）
        pattern1 = r'(\d{1,2})/(\d{1,2})[\s　]*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches1 = re.findall(pattern1, original_text)
        print(f"[DEBUG] pattern1マッチ: {matches1}")
        for m in matches1:
            month, day, sh, sm, eh, em = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:{sm if sm else '00'}"
            end_time = f"{int(eh):02d}:{em if em else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern1で追加: {new_date_entry}")
        pattern2 = r'[・\-]\s*(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})-([0-9]{1,2})時'
        matches2 = re.findall(pattern2, original_text)
        print(f"[DEBUG] pattern2マッチ: {matches2}")
        for m in matches2:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern2で追加: {new_date_entry}")
        pattern3 = r'(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})時?-([0-9]{1,2})時?'
        matches3 = re.findall(pattern3, original_text)
        print(f"[DEBUG] pattern3マッチ: {matches3}")
        for m in matches3:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern3で追加: {new_date_entry}")
        
        # 月が指定されていない場合（例：16日11:30-14:00）の処理
        pattern4 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches4 = re.findall(pattern4, original_text)
        print(f"[DEBUG] pattern4マッチ（日のみ）: {matches4}")
        for m in matches4:
            day, sh, sm, eh, em = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, int(day))
                    else:
                        dt = datetime(year, month+1, int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:{sm if sm else '00'}"
            end_time = f"{int(eh):02d}:{em if em else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern4で追加（日のみ）: {new_date_entry}")
        
        # 複数の時間帯が同じ日に指定されている場合（例：16日11:30-14:00/15:00-17:00）
        pattern5 = r'(\d{1,2})日\s*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})/([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches5 = re.findall(pattern5, original_text)
        print(f"[DEBUG] pattern5マッチ（日のみ複数時間帯）: {matches5}")
        for m in matches5:
            day, sh1, sm1, eh1, em1, sh2, sm2, eh2, em2 = m
            year = now.year
            month = now.month
            try:
                dt = datetime(year, month, int(day))
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, int(day))
                    else:
                        dt = datetime(year, month+1, int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            
            # 1つ目の時間帯
            start_time1 = f"{int(sh1):02d}:{sm1 if sm1 else '00'}"
            end_time1 = f"{int(eh1):02d}:{em1 if em1 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time1 and d.get('end_time') == end_time1 for d in new_dates):
                new_date_entry1 = {
                    'date': date_str,
                    'time': start_time1,
                    'end_time': end_time1,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry1['title'] = f"予定（{date_str} {start_time1}〜{end_time1}）"
                new_dates.append(new_date_entry1)
                print(f"[DEBUG] pattern5で追加（1つ目）: {new_date_entry1}")
            
            # 2つ目の時間帯
            start_time2 = f"{int(sh2):02d}:{sm2 if sm2 else '00'}"
            end_time2 = f"{int(eh2):02d}:{em2 if em2 else '00'}"
            if not any(d.get('date') == date_str and d.get('time') == start_time2 and d.get('end_time') == end_time2 for d in new_dates):
                new_date_entry2 = {
                    'date': date_str,
                    'time': start_time2,
                    'end_time': end_time2,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry2['title'] = f"予定（{date_str} {start_time2}〜{end_time2}）"
                new_dates.append(new_date_entry2)
                print(f"[DEBUG] pattern5で追加（2つ目）: {new_date_entry2}")
        
        # より柔軟な日付解析：改行やスペースで区切られた複数の日付に対応
        # 例：「16日11:30-14:00/15:00-17:00\n17日18:00-19:00\n18日9:00-10:00/16:00-16:30/17:30-18:00」
        lines = original_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 各行から日付を抽出
            day_match = re.search(r'(\d{1,2})日', line)
            if not day_match:
                continue
                
            day = int(day_match.group(1))
            year = now.year
            month = now.month
            
            try:
                dt = datetime(year, month, day)
                # 過去の日付の場合は来月として扱う
                if dt < now:
                    if month == 12:
                        dt = datetime(year+1, 1, day)
                    else:
                        dt = datetime(year, month+1, day)
            except Exception:
                continue
                
            date_str = dt.strftime('%Y-%m-%d')
            
            # 時間帯を抽出（複数の時間帯に対応）
            time_pattern = r'([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
            time_matches = re.findall(time_pattern, line)
            
            for time_match in time_matches:
                sh, sm, eh, em = time_match
                start_time = f"{int(sh):02d}:{sm if sm else '00'}"
                end_time = f"{int(eh):02d}:{em if em else '00'}"
                
                if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                    new_date_entry = {
                        'date': date_str,
                        'time': start_time,
                        'end_time': end_time,
                        'description': ''
                    }
                    if parsed.get('task_type') == 'add_event':
                        new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                    new_dates.append(new_date_entry)
                    print(f"[DEBUG] 柔軟な日付解析で追加: {new_date_entry}")
        
        # 本日/今日の処理を追加（AIが既に予定を作成していない場合のみ）
        if ('本日' in original_text or '今日' in original_text) and not new_dates:
            date_str = now.strftime('%Y-%m-%d')
            
            # 時間の抽出
            time_pattern = r'(本日|今日)(\d{1,2})時'
            time_match = re.search(time_pattern, original_text)
            
            if time_match:
                hour = int(time_match.group(2))
                start_time = f"{hour:02d}:00"
                end_time = f"{hour+1:02d}:00"
                
                # タイトルを抽出
                title_parts = original_text.split()
                title = ""
                for part in title_parts:
                    if part in ['移動', '移動あり', '移動時間', '移動必要']:
                        break
                    if not re.match(r'^\d{1,2}時$', part) and part not in ['本日', '今日']:
                        if title:
                            title += " "
                        title += part
                
                if not title:
                    title = "予定"
                
                print(f"[DEBUG] 抽出されたタイトル: '{title}'")
                
                # メイン予定を作成
                main_event = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'title': title,
                    'description': ''
                }
                
                new_dates.append(main_event)
                print(f"[DEBUG] 本日/今日の予定を追加: {main_event}")
        
        print(f"[DEBUG] new_dates(正規表現追加後): {new_dates}")
        
        # 移動時間の自動追加処理（予定追加の場合のみ）
        if parsed.get('task_type') == 'add_event':
            new_dates = self._add_travel_time(new_dates, original_text)
        else:
            print(f"[DEBUG] 空き時間確認のため、移動時間の自動追加をスキップ")
        
        parsed['dates'] = new_dates
        return parsed
    
    def _add_travel_time(self, dates, original_text):
        """移動時間を自動追加する処理"""
        from datetime import datetime, timedelta
        import pytz
        
        # 移動キーワードをチェック
        travel_keywords = ['移動', '移動あり', '移動時間', '移動必要']
        has_travel = any(keyword in original_text for keyword in travel_keywords)
        
        print(f"[DEBUG] 移動時間チェック: original_text='{original_text}', has_travel={has_travel}")
        print(f"[DEBUG] 移動キーワード: {travel_keywords}")
        
        if not has_travel:
            print(f"[DEBUG] 移動キーワードが見つからないため、移動時間を追加しません")
            return dates
        
        print(f"[DEBUG] 移動時間の自動追加を開始")
        
        jst = pytz.timezone('Asia/Tokyo')
        new_dates = []
        
        for date_info in dates:
            # 元の予定を追加
            new_dates.append(date_info)
            
            # 移動時間を追加するかチェック
            if self._should_add_travel_time(date_info, original_text):
                travel_events = self._create_travel_events(date_info, jst)
                
                # 移動時間の重複チェック
                for travel_event in travel_events:
                    is_duplicate = False
                    for existing_date in new_dates:
                        if (existing_date.get('date') == travel_event.get('date') and 
                            existing_date.get('time') == travel_event.get('time') and 
                            existing_date.get('end_time') == travel_event.get('end_time')):
                            is_duplicate = True
                            print(f"[DEBUG] 重複する移動時間をスキップ: {travel_event}")
                            break
                    
                    if not is_duplicate:
                        new_dates.append(travel_event)
                        print(f"[DEBUG] 移動時間を追加: {travel_event}")
        
        return new_dates
    
    def _should_add_travel_time(self, date_info, original_text):
        """移動時間を追加すべきかチェック"""
        # 移動キーワードが含まれている場合のみ追加
        travel_keywords = ['移動', '移動あり', '移動時間', '移動必要']
        result = any(keyword in original_text for keyword in travel_keywords)
        print(f"[DEBUG] _should_add_travel_time: original_text='{original_text}', result={result}")
        return result
    
    def _create_travel_events(self, main_event, jst):
        """移動時間の予定を作成"""
        from datetime import datetime, timedelta
        
        print(f"[DEBUG] _create_travel_events開始: main_event={main_event}")
        travel_events = []
        date_str = main_event['date']
        start_time = main_event['time']
        end_time = main_event['end_time']
        
        # 開始時間と終了時間をdatetimeオブジェクトに変換
        start_dt = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
        end_dt = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
        
        # 移動前の予定（1時間前）
        travel_before_dt = start_dt - timedelta(hours=1)
        travel_before_end_dt = start_dt
        
        travel_before_event = {
            'date': date_str,
            'time': travel_before_dt.strftime('%H:%M'),
            'end_time': travel_before_end_dt.strftime('%H:%M'),
            'title': '移動時間（往路）',
            'description': '移動のための時間'
        }
        travel_events.append(travel_before_event)
        
        # 移動後の予定（1時間後）
        travel_after_dt = end_dt
        travel_after_end_dt = end_dt + timedelta(hours=1)
        
        travel_after_event = {
            'date': date_str,
            'time': travel_after_dt.strftime('%H:%M'),
            'end_time': travel_after_end_dt.strftime('%H:%M'),
            'title': '移動時間（復路）',
            'description': '移動のための時間'
        }
        travel_events.append(travel_after_event)
        
        print(f"[DEBUG] 作成された移動時間イベント: {travel_events}")
        return travel_events
    
    def extract_event_info(self, text):
        """イベント追加用の情報を抽出します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "あなたはイベント情報抽出の専門家です。ユーザーのテキストからイベントのタイトルと日時を抽出し、以下のJSON形式で返してください。\n\n"
                "抽出ルール:\n"
                "1. イベントのタイトルは、直前の人名や主語、会議名なども含めて、できるだけ長く・具体的に抽出してください。\n"
                "   例:『田中さんとMTG 新作アプリの件』→タイトル:『田中さんとMTG』、説明:『新作アプリの件』\n"
                "2. 開始日時と終了日時を抽出（終了時間が明示されていない場合は1時間後をデフォルトとする）\n"
                "3. 日本語の日付表現を具体的な日付に変換\n"
                "4. 時間表現を24時間形式に変換\n"
                "5. タイムゾーンは日本時間（JST）を想定\n\n"
                "出力形式:\n"
                "{\n  \"title\": \"イベントタイトル\",\n  \"start_datetime\": \"2024-01-15T09:00:00\",\n  \"end_datetime\": \"2024-01-15T10:00:00\",\n  \"description\": \"説明（オプション）\"\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1
            )
            result = response.choices[0].message.content
            parsed = self._parse_ai_response(result)
            # --- タイトルが短すぎる場合は人名や主語＋MTGなどを含めて補完 ---
            if parsed and isinstance(parsed, dict) and 'title' in parsed:
                title = parsed['title']
                # 例: "MTG"や"会議"など短い場合は元テキストから人名＋MTGを抽出
                if title and len(title) <= 4:
                    import re
                    # 例: "田中さんとMTG" "佐藤さん会議" "山田さんMTG" など
                    m = re.search(r'([\w一-龠ぁ-んァ-ン]+さん[と]?\s*MTG|[\w一-龠ぁ-んァ-ン]+さん[と]?\s*会議)', text)
                    if m:
                        parsed['title'] = m.group(1)
            return parsed
        except Exception as e:
            return {"error": f"AI処理エラー: {str(e)}"}
    
    def format_calendar_response(self, events_info):
        """カレンダー情報を読みやすい形式にフォーマットします"""
        if not events_info:
            return "📅 指定された日付に予定はありません。"
        
        response = "📅 カレンダー情報\n\n"
        
        for day_info in events_info:
            if 'error' in day_info:
                response += f"❌ {day_info['date']}: {day_info['error']}\n\n"
                continue
            
            date = day_info['date']
            events = day_info['events']
            
            if not events:
                response += f"📅 {date}: 予定なし（空いています）\n\n"
            else:
                response += f"📅 {date}:\n"
                for event in events:
                    start_time = self._format_datetime(event['start'])
                    end_time = self._format_datetime(event['end'])
                    response += f"  • {event['title']} ({start_time} - {end_time})\n"
                response += "\n"
        
        return response
    
    def _format_datetime(self, datetime_str):
        """日時文字列を読みやすい形式にフォーマットします"""
        try:
            dt = parser.parse(datetime_str)
            return dt.strftime('%m/%d %H:%M')
        except:
            return datetime_str
    
    def format_event_confirmation(self, success, message, event_info):
        """
        イベント追加結果をフォーマットします
        予定が入っている場合：
        ❌予定が入っています！\n\n• タイトル (MM/DD HH:MM - HH:MM)
        予定を追加した場合：
        ✅予定を追加しました！\n\n📅タイトル\nM/D（曜）HH:MM〜HH:MM
        """
        if success:
            response = "✅予定を追加しました！\n\n"
            if event_info:
                title = event_info.get('title', '')
                start = event_info.get('start')
                end = event_info.get('end')
                if start and end:
                    from datetime import datetime
                    import pytz
                    jst = pytz.timezone('Asia/Tokyo')
                    start_dt = datetime.fromisoformat(start).astimezone(jst)
                    end_dt = datetime.fromisoformat(end).astimezone(jst)
                    weekday = "月火水木金土日"[start_dt.weekday()]
                    date_str = f"{start_dt.month}/{start_dt.day}（{weekday}）"
                    time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
                    response += f"📅{title}\n{date_str}{time_str}"
        else:
            response = "❌予定が入っています！\n\n"
            if event_info and isinstance(event_info, list):
                for event in event_info:
                    title = event.get('title', '')
                    start = event.get('start')
                    end = event.get('end')
                    if start and end:
                        from datetime import datetime
                        import pytz
                        jst = pytz.timezone('Asia/Tokyo')
                        start_dt = datetime.fromisoformat(start).astimezone(jst)
                        end_dt = datetime.fromisoformat(end).astimezone(jst)
                        date_str = f"{start_dt.month:02d}/{start_dt.day:02d}"
                        time_str = f"{start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')}"
                        response += f"• {title} ({date_str} {time_str})\n"
        return response
    
    def check_multiple_dates_availability(self, dates_info):
        """複数の日付の空き時間を確認するための情報を抽出します"""
        try:
            now_jst = self._get_jst_now_str()
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "複数の日付の空き時間確認リクエストを処理してください。以下のJSON形式で返してください。\n\n"
                "出力形式:\n"
                "{\n  \"dates\": [\n    {\n      \"date\": \"2024-01-15\",\n      \"time_range\": \"09:00-18:00\"\n    }\n  ]\n}\n"
            )
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": dates_info
                    }
                ],
                temperature=0.1
            )
            
            result = response.choices[0].message.content
            return self._parse_ai_response(result)
            
        except Exception as e:
            return {"error": f"AI処理エラー: {str(e)}"}
    
    def format_free_slots_response(self, free_slots_by_date):
        """
        free_slots_by_date: { 'YYYY-MM-DD': [{'start': '10:00', 'end': '11:00'}, ...], ... }
        指定フォーマットで空き時間を返す
        """
        jst = pytz.timezone('Asia/Tokyo')
        if not free_slots_by_date:
            return "✅空き時間はありませんでした。"
        response = "✅以下が空き時間です！\n\n"
        for date, slots in free_slots_by_date.items():
            dt = jst.localize(datetime.strptime(date, "%Y-%m-%d"))
            weekday = "月火水木金土日"[dt.weekday()]
            response += f"{dt.month}/{dt.day}（{weekday}）\n"
            if not slots:
                response += "・空き時間なし\n"
            else:
                for slot in slots:
                    response += f"・{slot['start']}〜{slot['end']}\n"
        return response
    
    def format_free_slots_response_by_frame(self, free_slots_by_frame):
        """
        free_slots_by_frame: [
            {'date': 'YYYY-MM-DD', 'start_time': 'HH:MM', 'end_time': 'HH:MM', 'free_slots': [{'start': 'HH:MM', 'end': 'HH:MM'}, ...]},
            ...
        ]
        日付ごとに空き時間をまとめて返す（重複枠・重複時間帯は除外）
        """
        print(f"[DEBUG] format_free_slots_response_by_frame開始")
        print(f"[DEBUG] 入力データ: {free_slots_by_frame}")
        
        jst = pytz.timezone('Asia/Tokyo')
        if not free_slots_by_frame:
            print(f"[DEBUG] free_slots_by_frameが空")
            return "✅空き時間はありませんでした。"
            
        # 日付ごとに空き時間をまとめる
        date_slots = {}
        for i, frame in enumerate(free_slots_by_frame):
            print(f"[DEBUG] フレーム{i+1}処理: {frame}")
            date = frame['date']
            slots = frame['free_slots']
            print(f"[DEBUG] フレーム{i+1}の空き時間: {slots}")
            
            if date not in date_slots:
                date_slots[date] = set()
            for slot in slots:
                date_slots[date].add((slot['start'], slot['end']))
                print(f"[DEBUG] 日付{date}に空き時間追加: {slot['start']}〜{slot['end']}")
                
        print(f"[DEBUG] 日付ごとの空き時間: {date_slots}")
        
        response = "✅以下が空き時間です！\n\n"
        for date in sorted(date_slots.keys()):
            slots = sorted(list(date_slots[date]))
            print(f"[DEBUG] 日付{date}の最終空き時間: {slots}")
            
            # 空き時間がない日付は表示しない
            if not slots:
                continue
                
            # 空き時間がある日付のみ表示
            dt = jst.localize(datetime.strptime(date, "%Y-%m-%d"))
            weekday = "月火水木金土日"[dt.weekday()]
            response += f"{dt.month}/{dt.day}（{weekday}）\n"
            
            for start, end in slots:
                response += f"・{start}〜{end}\n"
                    
        # 全ての日付で空き時間がない場合
        if response == "✅以下が空き時間です！\n\n":
            return "✅空き時間はありませんでした。"

        print(f"[DEBUG] 最終レスポンス: {response}")
        return response

    def format_events_response(self, events_info):
        """
        取得した予定リストを秘書風にフォーマットします
        events_info: [{'date': 'YYYY-MM-DD', 'events': [...], 'error': ...}, ...]
        """
        jst = pytz.timezone('Asia/Tokyo')
        if not events_info:
            return "指定された日付に予定はありませんでした。"

        response_parts = []
        all_empty = True

        for day_info in events_info:
            if 'error' in day_info:
                date_str = day_info.get('date', '')
                try:
                    dt = jst.localize(datetime.strptime(date_str, '%Y-%m-%d'))
                    weekday = "月火水木金土日"[dt.weekday()]
                    date_label = f"{dt.month}/{dt.day}（{weekday}）"
                except Exception:
                    date_label = date_str
                response_parts.append(f"📅 {date_label}\n取得エラー: {day_info['error']}")
                continue

            date_str = day_info.get('date', '')
            events = day_info.get('events', [])

            try:
                dt = jst.localize(datetime.strptime(date_str, '%Y-%m-%d'))
                weekday = "月火水木金土日"[dt.weekday()]
                date_label = f"{dt.month}/{dt.day}（{weekday}）"
            except Exception:
                date_label = date_str

            if not events:
                response_parts.append(f"📅 {date_label}は予定が入っていません！\n空いています😊")
            else:
                all_empty = False
                block = f"📅 {date_label}の予定\n\n"
                timed_events = []
                allday_events = []
                for event in events:
                    if event.get('is_all_day'):
                        allday_events.append(event)
                    else:
                        timed_events.append(event)

                for event in timed_events:
                    start = event.get('start', '')
                    end = event.get('end', '')
                    title = event.get('title', '予定')
                    try:
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone(jst)
                        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).astimezone(jst)
                        time_str = f"{start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
                    except Exception:
                        time_str = f"{start}〜{end}"
                    block += f"{time_str} {title}\n"

                for event in allday_events:
                    title = event.get('title', '終日予定')
                    block += f"終日 {title}\n"

                # 最後の予定の終了時刻を調べて「夕方以降は空き」などを追記
                if timed_events:
                    try:
                        last_event = timed_events[-1]
                        last_end = datetime.fromisoformat(last_event['end'].replace('Z', '+00:00')).astimezone(jst)
                        last_hour = last_end.hour
                        if last_hour <= 12:
                            block += "\n午後以降は空いています！"
                        elif last_hour <= 17:
                            block += "\n夕方以降は空いています！"
                    except Exception:
                        pass

                response_parts.append(block.rstrip())

        return "\n\n".join(response_parts)

    def format_suggest_response(self, title, free_slots_by_frame):
        """
        空き時間を提案する秘書風フォーマット
        free_slots_by_frame: [{'date': 'YYYY-MM-DD', 'start_time': ..., 'end_time': ..., 'free_slots': [...]}, ...]
        夜の時間帯（18:00以降）を優先して最大5候補を提示
        """
        print(f"[DEBUG] format_suggest_response開始: title={title}")
        jst = pytz.timezone('Asia/Tokyo')

        # 夜枠（18:00以降）の候補を集める
        evening_candidates = []
        other_candidates = []

        for frame in free_slots_by_frame:
            date_str = frame.get('date', '')
            slots = frame.get('free_slots', [])
            try:
                dt = jst.localize(datetime.strptime(date_str, '%Y-%m-%d'))
                weekday = "月火水木金土日"[dt.weekday()]
                date_label = f"{dt.month}/{dt.day}（{weekday}）"
            except Exception:
                date_label = date_str

            for slot in slots:
                start_str = slot.get('start', '')
                end_str = slot.get('end', '')
                try:
                    start_h = int(start_str.split(':')[0])
                    # 18時以降を夜枠とする
                    evening_start = max(start_str, '18:00') if start_h < 18 else start_str
                    # 夜枠の終了は22:00を上限とする
                    evening_end = min(end_str, '22:00')

                    if start_h < 18:
                        # スロットが18時をまたいでいる場合
                        if end_str > '18:00':
                            evening_candidates.append({
                                'label': f"{date_label} {evening_start}〜{evening_end}"
                            })
                        # 18時より前のスロット
                        day_end = min(end_str, '18:00')
                        if start_str < day_end:
                            other_candidates.append({
                                'label': f"{date_label} {start_str}〜{day_end}"
                            })
                    else:
                        # 18時以降のスロット
                        slot_end = min(end_str, '22:00')
                        if start_str < slot_end:
                            evening_candidates.append({
                                'label': f"{date_label} {start_str}〜{slot_end}"
                            })
                except Exception as e:
                    print(f"[DEBUG] format_suggest_response スロット処理エラー: {e}")
                    other_candidates.append({
                        'label': f"{date_label} {start_str}〜{end_str}"
                    })

        # 夜枠を優先して最大5件
        all_candidates = evening_candidates + other_candidates
        candidates = all_candidates[:5]

        if not candidates:
            return f"{title}を入れられる空き時間が見つかりませんでした。\n別の日程をお試しください。"

        response = f"以下が{title}の候補日程です✨\n\n"
        for c in candidates:
            response += f"{c['label']}\n"
        response += "\nご希望の日時はありますか？"

        print(f"[DEBUG] format_suggest_response完了: {response}")
        return response