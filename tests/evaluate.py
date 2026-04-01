import requests
import json
import time
import os

API_URL = "http://localhost:8000/ask"
TIMEOUT = 10  # seconds


def check_keywords(answer, keywords):
    answer = answer.lower()
    return any(k.lower() in answer for k in keywords)


def load_test_data():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(BASE_DIR, "test_data.json")

    if not os.path.exists(file_path):
        print(f"❌ Test data not found at: {file_path}")
        exit()

    with open(file_path) as f:
        return json.load(f)


def run_tests():
    tests = load_test_data()

    total = len(tests)
    passed = 0
    total_time = 0
    failed_tests = []

    print("\n🚀 Running Evaluation...\n")

    for i, test in enumerate(tests):
        print(f"🔹 Test {i+1}")

        start = time.time()

        try:
            response = requests.post(
                API_URL,
                json={
                    "question": test["question"],
                    "role": test["role"]
                },
                timeout=TIMEOUT
            )

            latency = time.time() - start
            total_time += latency

            if response.status_code != 200:
                print(f"❌ HTTP Error: {response.status_code}")
                failed_tests.append(i+1)
                continue

            data = response.json()
            answer = data.get("answer", "")

        except requests.exceptions.Timeout:
            print("❌ Request timed out")
            failed_tests.append(i+1)
            continue

        except Exception as e:
            print(f"❌ Error: {str(e)}")
            failed_tests.append(i+1)
            continue

        # ✅ Check correctness
        success = check_keywords(answer, test["expected_keywords"])

        if success:
            passed += 1
            print("✅ PASS")
        else:
            print("❌ FAIL")
            failed_tests.append(i+1)

        print(f"Q: {test['question']}")
        print(f"Role: {test['role']}")
        print(f"A: {answer[:120]}")
        print(f"Latency: {latency:.2f}s\n")

    # 📊 Final Results
    accuracy = (passed / total) * 100 if total > 0 else 0
    avg_latency = total_time / total if total > 0 else 0

    print("=" * 60)
    print(f"🎯 Total Tests: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {len(failed_tests)}")
    print(f"📊 Accuracy: {accuracy:.2f}%")
    print(f"⚡ Avg Latency: {avg_latency:.2f}s")
    print(f"❗ Failed Test IDs: {failed_tests}")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()