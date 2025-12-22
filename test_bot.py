#!/usr/bin/env python3
"""
LINE Calendar Bot テストスクリプト
システムの動作確認とデバッグ用
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

from calendar_service import GoogleCalendarService
import pytz

from ai_service import AIService

# 環境変数を読み込み
load_dotenv()

def test_config():
    """設定のテスト"""
    print("=== 設定テスト ===")
    
    required_vars = [
        'LINE_CHANNEL_ACCESS_TOKEN',
        'LINE_CHANNEL_SECRET', 
        'OPENAI_API_KEY'
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: 設定済み")
        else:
            print(f"❌ {var}: 未設定")
    
    # Google認証ファイルの確認
    creds_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
    if os.path.exists(creds_file):
        print(f"✅ Google認証ファイル: {creds_file} 存在")
    else:
        print(f"❌ Google認証ファイル: {creds_file} 不存在")
    
    print()

def test_ai_service():
    """AIサービスのテスト"""
    print("=== AIサービステスト ===")
    
    try:
        from ai_service import AIService
        
        ai_service = AIService()
        
        # 日時抽出テスト
        test_messages = [
            "明日と明後日の空き時間を教えて",
            "明日の午前9時から会議を追加して",
            "来週月曜日の14時から打ち合わせ"
        ]
        
        for message in test_messages:
            print(f"テストメッセージ: {message}")
            result = ai_service.extract_dates_and_times(message)
            print(f"結果: {result}")
            print()
            
    except Exception as e:
        print(f"❌ AIサービステストエラー: {e}")
        print()

def test_calendar_service():
    """カレンダーサービスのテスト"""
    print("=== カレンダーサービステスト ===")
    
    try:
        from calendar_service import GoogleCalendarService
        
        calendar_service = GoogleCalendarService()
        print("✅ Google Calendarサービス初期化成功")
        
        # 今日の日付を取得
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        
        # イベント取得テスト
        events_info = calendar_service.get_events_for_dates([today, tomorrow])
        print(f"今日と明日のイベント: {events_info}")
        print()
        
    except Exception as e:
        print(f"❌ カレンダーサービステストエラー: {e}")
        print()

def test_line_bot_handler():
    """LINE Botハンドラーのテスト"""
    print("=== LINE Botハンドラーテスト ===")
    
    try:
        from line_bot_handler import LineBotHandler
        
        handler = LineBotHandler()
        print("✅ LINE Botハンドラー初期化成功")
        print()
        
    except Exception as e:
        print(f"❌ LINE Botハンドラーテストエラー: {e}")
        print()

def test_flask_app():
    """Flaskアプリケーションのテスト"""
    print("=== Flaskアプリケーションテスト ===")
    
    try:
        from app import app
        
        with app.test_client() as client:
            # ヘルスチェック
            response = client.get('/health')
            print(f"ヘルスチェック: {response.status_code} - {response.json}")
            
            # テストエンドポイント
            response = client.get('/test')
            print(f"テストエンドポイント: {response.status_code} - {response.json}")
            
        print("✅ Flaskアプリケーションテスト成功")
        print()
        
    except Exception as e:
        print(f"❌ Flaskアプリケーションテストエラー: {e}")
        print()

def test_integration():
    """統合テスト"""
    print("=== 統合テスト ===")
    
    try:
        from ai_service import AIService
        from calendar_service import GoogleCalendarService
        
        ai_service = AIService()
        calendar_service = GoogleCalendarService()
        
        # テストメッセージ
        test_message = "明日の午前9時から会議を追加して"
        
        # AIでイベント情報を抽出
        event_info = ai_service.extract_event_info(test_message)
        print(f"イベント情報抽出: {event_info}")
        
        if 'error' not in event_info:
            # カレンダーに追加テスト（実際には追加しない）
            print("✅ 統合テスト成功")
        else:
            print("❌ イベント情報抽出に失敗")
        
        print()
        
    except Exception as e:
        print(f"❌ 統合テストエラー: {e}")
        print()

def test_find_free_slots_for_day():
    service = GoogleCalendarService()
    jst = pytz.timezone('Asia/Tokyo')
    # 予定: 20:00〜20:30
    events = [
        {'title': 'MTG', 'start': '2025-07-10T20:00:00+09:00', 'end': '2025-07-10T20:30:00+09:00'}
    ]
    start_dt = jst.localize(datetime.strptime('2025-07-10 18:00', '%Y-%m-%d %H:%M'))
    end_dt = jst.localize(datetime.strptime('2025-07-10 22:00', '%Y-%m-%d %H:%M'))
    free_slots = service.find_free_slots_for_day(start_dt, end_dt, events)
    print('free_slots:', free_slots)
    assert free_slots == [
        {'start': '18:00', 'end': '20:00'},
        {'start': '20:30', 'end': '22:00'}
    ], '空き枠分割ロジックにバグがあります'

def test_full_flow():
    ai = AIService()
    from calendar_service import GoogleCalendarService
    import pytz
    from datetime import datetime
    service = GoogleCalendarService()
    jst = pytz.timezone('Asia/Tokyo')
    # ユーザー入力
    user_message = '・7/10 9-10時\n・7/11 9-10時'
    ai_result = ai.extract_dates_and_times(user_message)
    print('ai_result:', ai_result)
    dates = ai_result.get('dates', [])
    if isinstance(dates, str):
        dates = json.loads(dates)
    free_slots_by_frame = []
    for date_info in dates:
        date_str = date_info.get('date')
        start_time = date_info.get('time')
        end_time = date_info.get('end_time')
        start_dt = jst.localize(datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M"))
        end_dt = jst.localize(datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M"))
        events = []  # 予定なしでテスト
        free_slots = service.find_free_slots_for_day(start_dt, end_dt, events)
        free_slots_by_frame.append({
            'date': date_str,
            'start_time': start_time,
            'end_time': end_time,
            'free_slots': free_slots
        })
    response_text = ai.format_free_slots_response_by_frame(free_slots_by_frame)
    print('response_text:\n', response_text)

def test_month_year_detection():
    """12月に1月と指定された場合、来年の1月を返すことをテスト"""
    print("=== 月のみ指定時の年判定テスト ===")

    ai = AIService()
    now = datetime.now(pytz.timezone('Asia/Tokyo'))

    # 現在が12月の場合のテストケース
    if now.month == 12:
        user_message = '1月の空き時間'
        ai_result = ai.extract_dates_and_times(user_message)
        print(f'テストメッセージ: {user_message}')
        print(f'AI結果: {ai_result}')

        if ai_result and 'dates' in ai_result:
            dates = ai_result.get('dates', [])
            if dates:
                first_date = dates[0].get('date', '')
                year = int(first_date.split('-')[0])
                month = int(first_date.split('-')[1])

                # 1月が来年（2026年）として認識されているか確認
                expected_year = now.year + 1
                if year == expected_year and month == 1:
                    print(f'✅ 成功: 1月が{expected_year}年として認識されました')
                else:
                    print(f'❌ 失敗: 1月が{year}年{month}月として認識されました（期待: {expected_year}年1月）')
            else:
                print('❌ 失敗: datesが空です')
        else:
            print('❌ 失敗: ai_resultにdatesがありません')
    else:
        print(f'現在の月が{now.month}月のため、このテストは12月のみ有効です')

    print()

def main():
    """メイン関数"""
    print("LINE Calendar Bot テスト開始")
    print("=" * 50)
    
    # 各テストを実行
    test_config()
    test_ai_service()
    test_calendar_service()
    test_line_bot_handler()
    test_flask_app()
    test_integration()
    
    print("=" * 50)
    print("テスト完了")
    
    # 起動方法の案内
    print("\n=== 起動方法 ===")
    print("1. 環境変数を設定してください")
    print("2. Google認証ファイルを配置してください")
    print("3. 以下のコマンドで起動してください:")
    print("   python app.py")
    print("\n4. ブラウザで http://localhost:5000/test にアクセスして設定を確認してください")

if __name__ == "__main__":
    test_find_free_slots_for_day()
    print('find_free_slots_for_dayテスト成功')
    test_full_flow()
    print('full_flowテスト成功')
    test_month_year_detection()
    print('month_year_detectionテスト成功') 