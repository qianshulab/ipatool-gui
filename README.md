# IPA Download Tool - 桌面版

基于 [ipatool](https://github.com/majd/ipatool) 的 PyQt6 图形化 iOS 应用下载工具。

## 功能特性

- 🔍 **应用搜索** - 搜索 App Store 应用
- 📥 **一键下载** - 支持 Bundle ID 和 App ID 下载
- 🎨 **现代界面** - 基于 PyQt6 的美观界面
- 💾 **下载管理** - 自定义下载路径
- 🔐 **账号管理** - 安全保存 Apple ID 凭据
- ⚙️ **配置管理** - 灵活的设置选项

## 系统要求

- **操作系统**: Windows 10/11, macOS 10.15+, Linux
- **Python**: 3.8+
- **ipatool**: 2.1.0+

## 安装步骤

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 ipatool

#### Windows

1. 从 [ipatool Releases](https://github.com/majd/ipatool/releases) 下载 `ipatool-*-windows-amd64.zip`
2. 解压到任意目录
3. 将 `ipatool.exe` 路径添加到系统 PATH，或在程序设置中指定路径

#### macOS

```bash
# 使用 Homebrew
brew tap majd/repo
brew install ipatool

# 或手动下载
wget https://github.com/majd/ipatool/releases/download/v2.1.3/ipatool-2.1.3-darwin-amd64.tar.gz
tar -xzf ipatool-2.1.3-darwin-amd64.tar.gz
sudo mv ipatool /usr/local/bin/
sudo chmod +x /usr/local/bin/ipatool
```

#### Linux

```bash
wget https://github.com/majd/ipatool/releases/download/v2.1.3/ipatool-2.1.3-linux-amd64.tar.gz
tar -xzf ipatool-2.1.3-linux-amd64.tar.gz
sudo mv ipatool /usr/local/bin/
sudo chmod +x /usr/local/bin/ipatool
```

### 3. 运行程序

```bash
python main.py
```

## 使用说明

### 首次使用

1. **登录 Apple ID**
   - 点击工具栏的"登录"按钮
   - 输入 Apple ID 邮箱
   - 输入**应用专用密码**（不是 Apple ID 密码！）
   - 可选择"记住凭据"保存到本地

2. **获取应用专用密码**
   - 访问 https://appleid.apple.com
   - 登录后进入"安全"部分
   - 在"应用专用密码"下，点击"生成密码..."
   - 输入标签（如"IPA Download Tool"）
   - 复制生成的密码（格式：xxxx-xxxx-xxxx-xxxx）

### 搜索应用

1. 切换到"🔍 搜索下载"标签页
2. 在搜索框输入应用名称或关键词
3. 点击"搜索"按钮
4. 从结果列表中选择应用，点击"下载"按钮

### 直接下载

1. 切换到"📥 直接下载"标签页
2. 输入应用的 Bundle ID（必需）或 App ID
3. 选择保存路径
4. 勾选"自动获取应用许可"（如果应用需要）
5. 点击"开始下载"按钮

### 常用应用 Bundle ID

- 微信: `com.tencent.xin`
- QQ: `com.tencent.mqq`
- 抖音: `com.ss.iphone.ugc.Aweme`
- 淘宝: `com.taobao.taobao4iphone`
- 支付宝: `com.alipay.iphoneclient`

## 配置说明

配置文件保存在 `config.json`，包含以下选项：

```json
{
  "apple_id": {
    "email": "your-email@example.com",
    "password": ""
  },
  "ipatool_path": "",
  "download_path": "C:\\Users\\YourName\\Downloads\\IPA",
  "auto_purchase": true,
  "remember_credentials": false
}
```

## 故障排查

### ipatool 未找到

**问题**: 提示"未找到 ipatool"

**解决**:
1. 确认已安装 ipatool
2. 将 ipatool 添加到系统 PATH
3. 或在"设置"中指定 ipatool 完整路径

### 登录失败

**问题**: 登录时提示失败

**检查**:
1. 确认使用的是**应用专用密码**，不是 Apple ID 密码
2. 确认 Apple ID 已启用双因素认证
3. 网络连接正常

### 下载失败

**常见原因**:
1. 未登录 Apple ID
2. Bundle ID 不正确
3. 应用未在该地区的 App Store 上架
4. 应用需要购买但未获取许可

## 安全说明

⚠️ **重要提示**:

1. 仅下载你已购买或有权使用的应用
2. 应用专用密码安全性高于普通密码
3. 配置文件以明文存储，注意保护
4. 不要在公共计算机上使用"记住凭据"功能
5. IPA 文件已加密，需要对应 Apple ID 才能安装

## 开发说明

### 项目结构

```
ipadownload/
├── main.py              # 程序入口
├── requirements.txt     # Python 依赖
├── config.json          # 配置文件
├── core/                # 核心模块
│   ├── ipatool.py      # ipatool 封装
│   └── config.py       # 配置管理
└── ui/                  # 界面模块
    ├── main_window.py  # 主窗口
    ├── dialogs.py      # 对话框
    └── workers.py      # 后台线程
```

### 打包为可执行文件

使用 PyInstaller 打包：

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包（Windows）
pyinstaller --name="IPA Download Tool" --windowed --onefile main.py

# 打包（macOS）
pyinstaller --name="IPA Download Tool" --windowed --onefile main.py

# 打包（Linux）
pyinstaller --name="IPA Download Tool" --onefile main.py
```

## 许可证

MIT License

## 致谢

- [ipatool](https://github.com/majd/ipatool) - 核心下载工具
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI 框架
- Apple Inc. - App Store 服务

## 支持

如有问题或建议，请提交 Issue。

⚠️ **免责声明**: 本工具仅供学习和研究使用。请遵守 Apple 的服务条款和当地法律法规。
