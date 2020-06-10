from tino import run

if __name__ == "__main__":
    run("bench_echo:api", workers=1, host="localhost", port=7777)
