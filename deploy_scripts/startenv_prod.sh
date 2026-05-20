echo "start_env==>开始：$(date '+%Y-%m-%d %H:%M:%S') "

# 检查并加载环境变量文件
ENV_FILE=".env.prod"
if [ -f "$ENV_FILE" ]; then
    echo "加载环境配置文件: $ENV_FILE"
    export $(grep -v '^#' $ENV_FILE | xargs)
else
    echo "警告: 环境配置文件 $ENV_FILE 不存在，将使用默认配置"
    export APP_CODE_ENV_NAME="prod"
fi

# 重新加载 shell 配置
source ~/.bashrc

pip install uv -i http://devpi.corp.qunar.com/qunar/dev/+simple/ --trusted-host devpi.corp.qunar.com

uv pip install -r requirements.txt --index-url http://devpi.corp.qunar.com/qunar/dev/+simple/ --trusted-host devpi.corp.qunar.com --system

# 确保环境变量被设置（如果 .env 文件不存在的话）
if [ -z "$APP_CODE_ENV_NAME" ]; then
    export APP_CODE_ENV_NAME="prod"
fi


# 1. 配置参数
# 如果文件路径发生变化，只需修改这里
SOURCE_TAR="/shared_data/app_data/www/default.qunar.com/webapps/ROOT/source/ffmpeg-release-amd64-static.tar.xz"
INSTALL_DIR="/usr/local/ffmpeg"
BIN_LINK="/usr/bin/ffmpeg"

echo "开始执行 FFmpeg 部署脚本..."

# 2. 检查 FFmpeg 是否已安装
if command -v ffmpeg &> /dev/null; then
    echo "检测到系统已安装 FFmpeg: $(ffmpeg -version | head -n 1)"
    echo "跳过安装步骤。"
    exit 0
fi

# 3. 检查源文件是否存在
if [ ! -f "$SOURCE_TAR" ]; then
    echo "错误: 未在路径 $SOURCE_TAR 找到压缩包！"
    echo "请确认下载是否成功或路径是否正确。"
    exit 1
fi

# 4. 创建安装目录并解压
echo "正在创建安装目录: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

echo "正在解压并部署文件..."
# --strip-components 1 用于去除压缩包内的第一层文件夹名
tar -xJf "$SOURCE_TAR" -C "$INSTALL_DIR" --strip-components 1

if [ $? -eq 0 ]; then
    echo "解压完成。"
else
    echo "错误: 解压失败，请检查文件完整性。"
    exit 1
fi

# 5. 创建系统软链接
echo "配置系统命令快捷方式..."
ln -sf "$INSTALL_DIR/ffmpeg" /usr/bin/ffmpeg
ln -sf "$INSTALL_DIR/ffprobe" /usr/bin/ffprobe
chmod +x /usr/local/ffmpeg/ffmpeg /usr/local/ffmpeg/ffprobe

# 6. 配置环境变量 (写入 /etc/profile 确保所有用户生效)
if ! grep -q "$INSTALL_DIR" /etc/profile; then
    echo "正在将 FFmpeg 路径写入 /etc/profile..."
    echo "export PATH=$INSTALL_DIR:\$PATH" >> /etc/profile
    # 注意：在脚本中 source /etc/profile 仅对当前脚本进程生效
    # 需要手动在终端 source 一次或者重新登录
fi

# 7. 最终验证
echo "------------------------------------------------"
if ffmpeg -version &> /dev/null; then
    echo "✅ FFmpeg 自动化安装成功！"
    ffmpeg -version | head -n 1
else
    echo "❌ 安装后验证失败，请手动检查 /usr/bin/ffmpeg 链接。"
fi
echo "------------------------------------------------"



export RUN_CMD="python -m src.main"

echo "当前环境: $APP_CODE_ENV_NAME"
echo "start_env==>结束：$(date '+%Y-%m-%d %H:%M:%S') "
