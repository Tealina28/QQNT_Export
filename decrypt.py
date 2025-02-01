import os, hashlib, time
from pysqlcipher3 import dbapi2 as sqlite

# 数据库批量解密

def getKeys(uid, path):
    keys = {}
    for file in os.listdir(path):
        if file.endswith(".db"):
            with open(os.path.join(path, file), "rb") as f:
                data = str(f.read(54)[-8:])[2:-1]
                if not data.isprintable():
                    break
                uidHash = hashlib.md5(uid.encode()).hexdigest()
                keys[file] = hashlib.md5((uidHash + data).encode()).hexdigest()
    return keys


def removeHead(keys, path):
    newPath = os.path.join(os.path.dirname(path), "decrypt_" + str(int(time.time())))
    try:
        os.mkdir(newPath)
    except OSError as e:
        print(f"创建目录 {newPath} 失败")
        return None
    for db, _ in keys.items():
        source_file = os.path.join(path, db)
        dest_file = os.path.join(newPath, "en_" + db)
        try:
            with open(source_file, "rb") as f:
                f.seek(1024)
                with open(dest_file, "wb") as newf:
                    newf.write(f.read())
        except OSError as e:
            print(f"处理文件 {db} 失败")
            continue
    return newPath


def decryptDB(keys, path):
    count = 0

    def remove_file(file_path):
        try:
            os.remove(file_path)
            return True
        except:
            return False

    for db, key in keys.items():
        encrypted_db = os.path.join(path, "en_" + db)
        unencrypted_db = os.path.join(path, db)
        if db.startswith("gpro_v1-6_u"):
            print(f"暂不支持解密 {db}")
            continue
        else:
            print(f"正在解密 {db}")
        if not os.path.exists(unencrypted_db):
            conn = sqlite.connect(unencrypted_db)
            conn.close()
        conn = None
        try:
            conn = sqlite.connect(encrypted_db)
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA key = '{key}';")
            cursor.execute("PRAGMA cipher_page_size = 4096;")
            cursor.execute("PRAGMA kdf_iter = 4000;")
            cursor.execute("PRAGMA cipher_hmac_algorithm = HMAC_SHA1;")
            cursor.execute("PRAGMA cipher_default_kdf_algorithm = PBKDF2_HMAC_SHA512;")
            cursor.execute("PRAGMA cipher = 'aes-256-cbc';")
            cursor.execute("BEGIN;")
            cursor.execute(f"ATTACH DATABASE '{unencrypted_db}' AS plaintext KEY '';")
            cursor.execute("SELECT sqlcipher_export('plaintext');")
            cursor.execute("DETACH DATABASE plaintext;")
            conn.commit()
            cursor.close()
            conn.close()
            count += 1
        except Exception as e:
            print(f"失败：{db}")
        finally:
            if conn:
                conn.close()
            if not remove_file(encrypted_db):
                print(f"最终删除文件 {encrypted_db} 失败，请手动删除")
    return count, len(keys)


def decrypt(uid, path):
    print("开始解密数据库，请稍等...")
    keys = getKeys(uid, path)
    newPath = removeHead(keys, path)
    count, total = decryptDB(keys, newPath)
    print(f"成功解密({count}/{total}), 解密后数据库的路径为 {newPath}")


if __name__ == "__main__":
    decrypt(uid, path)