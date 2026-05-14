# A5Gate - Shell 代理网关

客户端提交 shell 命令 → Gateway 暂存 → 工作机轮询执行 → 结果回传 → 客户端查询。

## 架构

```
客户端 ──HTTPS──▶ Gateway ◀──HTTP── 工作机
  │                  │                  │
  │ POST /api/command│ SQLite           │ su - user -c "cmd"
  │ GET  /api/command/<reqid>           │
```

## 安装

```bash
pip install -r requirements.txt
```

## 启动

### Gateway

```bash
# HTTP (无 TLS)
python gateway.py --port 8000

# HTTPS (Cloudflare origin)
python gateway.py --cert cert.pem --key key.pem --port 8000
```

### 工作机（需 root 权限以切换用户）

```bash
python worker.py --gateway https://<gateway-host>:8000 [--insecure]
```

### 客户端

```bash
# 提交命令
python client.py submit --user nobody "ls -la"

# 从管道提交
echo "cat /etc/passwd" | python client.py submit --user nobody

# 提交并等待结果
python client.py run --user nobody "sleep 5 && date"

# 查询结果
python client.py query <reqid>
```

## 认证 (HMAC)

```bash
export SHARED_SECRET=your-secret-key
```

Gateway 设了 `SHARED_SECRET` 后，所有请求需带 HMAC 签名，否则返回 401。Client / Worker 需设相同密钥。

## 选项

| 参数 | 说明 |
|------|------|
| `--gateway URL` | Gateway 地址 (默认 `http://localhost:8000`) |
| `--user NAME` | 工作机执行命令的系统用户 (必填，禁止 root) |
| `--insecure` | 禁用 TLS 证书验证 (直连 Gateway 时) |
| `--timeout SEC` | `run` 子命令最大等待秒数 (默认 60) |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/command` | 提交命令 → `{"reqid":"..."}` |
| GET | `/api/command/next` | 工作机获取下一条待执行命令 |
| POST | `/api/command/{reqid}/result` | 工作机回传执行结果 |
| GET | `/api/command/{reqid}` | 按 reqid 查询状态和结果 |
