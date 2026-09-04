"""
Quick manual test for db.py -- run this once to see the database
functions working, before we touch bot.py at all.

Run it with:  python test_db.py
"""

import db

db.init_db()
print("1. init_db() ran -- bot_database.db file should now exist.")

test_chat_id = 12345
db.clear_history(test_chat_id)  # start clean in case you run this twice

db.save_message(test_chat_id, "user", "Hello, bot!")
db.save_message(test_chat_id, "assistant", "Hello! How can I help?")
db.save_message(test_chat_id, "user", "What's the bitcoin price?")
print("2. Saved 3 test messages.")

history = db.load_history(test_chat_id)
print("3. load_history() returned:")
for message in history:
    print(f"   {message['role']}: {message['content']}")

db.clear_history(test_chat_id)
history_after_clear = db.load_history(test_chat_id)
print(f"4. After clear_history(), history is now: {history_after_clear} (should be empty list)")

print("\nAll checks passed if you see 3 messages in step 3 and an empty list in step 4.")
