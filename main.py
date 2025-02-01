import sys
from decode import decode
from decrypt import decrypt


def main():
    if len(sys.argv) < 3:
        print("Usage: python main.py <mode> <path> [uid]")
        print("Modes: decode, decrypt")
        return

    mode = sys.argv[1]
    path = sys.argv[2]

    if mode == "decode":
        decode(path)
    elif mode == "decrypt":
        if len(sys.argv) < 4:
            print("Usage: python main.py decrypt <path> <uid>")
            return
        uid = sys.argv[3]
        decrypt(uid, path)
    else:
        print(f"Unknown mode: {mode}")
        print("Modes: decode, decrypt")

if __name__ == "__main__":
    main()