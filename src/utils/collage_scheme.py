import inspect
import sys

# ----------------------------------------------------------------------------
# 配置:
# 确保这个模块名 (MODULE_NAME) 与您保存拼图函数的文件名 (不含.py) 一致
# ----------------------------------------------------------------------------
MODULE_NAME = "collage_scheme"  # 修正：去掉.py扩展名
OUTPUT_JSON = "collage_layouts_map.json"

import logging
import os

from PIL import Image

logger = logging.getLogger(__name__)


# --- 核心辅助函数 (来自您的提供，保持不变) ---

def resize_and_crop_to_fill(img, target_size):
    """
    (这是我们之前用过的辅助函数)
    将图片调整大小并从中心裁剪，以完全填充目标尺寸，保持宽高比。
    """
    # 确保 target_size 是整数
    target_width, target_height = int(target_size[0]), int(target_size[1])

    # 修复：确保 target_width 和 target_height 不为0
    if target_width <= 0 or target_height <= 0:
        print(f"警告：目标尺寸无效 ({target_width}x{target_height})。使用默认 100x100。")
        target_width, target_height = 100, 100

    img_ratio = img.width / img.height
    target_ratio = target_width / target_height

    try:
        if img_ratio > target_ratio:
            # 图片比目标“更宽”
            new_height = target_height
            new_width = int(new_height * img_ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            # 从中心裁剪
            left = (new_width - target_width) / 2
            img = img.crop((left, 0, left + target_width, target_height))
        else:
            # 图片比目标“更高”
            new_width = target_width
            new_height = int(new_width / img_ratio)
            if new_height == 0: new_height = 1  # 避免除以0
            img = img.resize((new_width, new_height), Image.LANCZOS)
            # 从中心裁剪
            top = (new_height - target_height) / 2
            img = img.crop((0, top, target_width, top + target_height))
    except ValueError as e:
        print(f"错误：调整图片大小时出错 (img_size={img.size}, target={target_size}): {e}")
        # 返回一个安全的占位符
        img = Image.new('RGB', (target_width, target_height), (200, 200, 200))

    return img


def _load_images(paths):
    """辅助函数：安全地加载图片路径列表"""
    images = []
    all_loaded = True
    for path in paths:
        if not path or not os.path.exists(path):
            print(f"错误：找不到图片路径 {path}。")
            all_loaded = False
            continue
        try:
            img = Image.open(path).convert('RGB')
            images.append(img)
        except Exception as e:
            print(f"警告：加载图片 {path} 失败: {e}")
            all_loaded = False
    return images, all_loaded


def _save_canvas(canvas, output_path):
    """辅助函数：保存画布"""
    try:
        canvas.save(output_path, quality=95)
        print(f"拼图成功！已保存至: {output_path}\n")
    except Exception as e:
        print(f"错误：保存拼图失败: {e}")


def create_collage_1_images(path_main, output_path, bg_color=(255, 255, 255)):
    """
    创建 1 张图的布局（用于单独展示高质量图片）。
    布局：单张图片将（从中心）裁剪并缩放，以**完全填满**整个 3:4 的竖屏画布。

    参数映射:
    - path_main: 要单独展示的主图
    """
    paths = [path_main]
    # 假设 _load_images 是一个已定义的辅助函数，用于加载图片
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 1:
        print("错误：单图布局需要1张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    # 注意：单图布局通常不需要边距 (MARGIN = 0)

    # 画布背景色在图片加载失败时可见
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 1. 准备主图
    # 目标尺寸是整个画布
    target_size = (CANVAS_WIDTH, CANVAS_HEIGHT)

    # 假设 resize_and_crop_to_fill 是一个已定义的辅助函数
    img_main = resize_and_crop_to_fill(images[0], target_size)

    # 2. 粘贴主图
    # 从 (0, 0) 坐标开始粘贴，填满画布
    canvas.paste(img_main, (0, 0))

    # 假设 _save_canvas 是一个已定义的辅助函数
    _save_canvas(canvas, output_path)


# --- 2张图布局 ---

def create_collage_2_images(path_top, path_bottom, output_path, bg_color=(255, 255, 255)):
    """
    创建 2 张图的拼图。
    布局：上/下 垂直堆叠。

    参数映射:
    - path_top:    位于顶部的横向图片
    - path_bottom: 位于底部的横向图片
    """
    images, loaded = _load_images([path_top, path_bottom])
    if not loaded or len(images) != 2:
        print("错误：2图拼图需要2张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 仅保留图片之间的间距，外层无边距
    cell_w = CANVAS_WIDTH
    cell_h = (CANVAS_HEIGHT - MARGIN) // 2

    img_top = resize_and_crop_to_fill(images[0], (cell_w, cell_h))
    canvas.paste(img_top, (0, 0))

    img_bottom = resize_and_crop_to_fill(images[1], (cell_w, cell_h))
    canvas.paste(img_bottom, (0, cell_h + MARGIN))

    _save_canvas(canvas, output_path)


# --- 3张图布局 ---

def create_collage_3_images(path_hero, path_bottom_left, path_bottom_right, output_path, bg_color=(255, 255, 255)):
    """
    创建 3 张图的拼图。
    新布局：顶部一张横向主图，底部两张并排（更均衡，视觉更清爽）。

    参数映射:
    - path_hero:   顶部主图（横向）
    - path_bottom_left:  底部左图
    - path_bottom_right: 底部右图
    """
    images, loaded = _load_images([path_hero, path_bottom_left, path_bottom_right])
    if not loaded or len(images) != 3:
        print("错误：3图拼图需要3张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 3
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 顶部主图：占据约 60% 高度，底部两图并排
    hero_h = int(CANVAS_HEIGHT * 0.60)
    hero_w = CANVAS_WIDTH
    img_hero = resize_and_crop_to_fill(images[0], (hero_w, hero_h))
    canvas.paste(img_hero, (0, 0))

    # 底部两图尺寸与位置
    cell_w = (CANVAS_WIDTH - MARGIN) // 2
    cell_h = CANVAS_HEIGHT - hero_h - MARGIN
    bottom_y = hero_h + MARGIN

    img_bl = resize_and_crop_to_fill(images[1], (cell_w, cell_h))
    canvas.paste(img_bl, (0, bottom_y))

    img_br = resize_and_crop_to_fill(images[2], (cell_w, cell_h))
    canvas.paste(img_br, (cell_w + MARGIN, bottom_y))

    _save_canvas(canvas, output_path)


# --- 4张图布局 ---

def create_collage_4_images(path_tl, path_tr, path_bl, path_br, output_path, bg_color=(255, 255, 255)):
    """
    创建 4 张图的拼图。
    布局：2x2 田字格。

    参数映射:
    - path_tl: 左上角 (Top-Left)
    - path_tr: 右上角 (Top-Right)
    - path_bl: 左下角 (Bottom-Left)
    - path_br: 右下角 (Bottom-Right)
    """
    images, loaded = _load_images([path_tl, path_tr, path_bl, path_br])
    if not loaded or len(images) != 4:
        print("错误：4图拼图需要4张有效的图片。")
        return

    CANVAS_WIDTH = 1000
    CANVAS_HEIGHT = 1000
    MARGIN = 1
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 2x2 田字格：仅图与图之间留 MARGIN，边界不留白。
    # 为避免整除造成右/下边界出现 1px 空白，左右/上下格子分别按剩余填满。
    cell_w_left = (CANVAS_WIDTH - MARGIN) // 2
    cell_w_right = CANVAS_WIDTH - MARGIN - cell_w_left
    cell_h_top = (CANVAS_HEIGHT - MARGIN) // 2
    cell_h_bottom = CANVAS_HEIGHT - MARGIN - cell_h_top

    x1 = 0
    x2 = cell_w_left + MARGIN
    y1 = 0
    y2 = cell_h_top + MARGIN

    img_tl = resize_and_crop_to_fill(images[0], (cell_w_left, cell_h_top))
    canvas.paste(img_tl, (x1, y1))

    img_tr = resize_and_crop_to_fill(images[1], (cell_w_right, cell_h_top))
    canvas.paste(img_tr, (x2, y1))

    img_bl = resize_and_crop_to_fill(images[2], (cell_w_left, cell_h_bottom))
    canvas.paste(img_bl, (x1, y2))

    img_br = resize_and_crop_to_fill(images[3], (cell_w_right, cell_h_bottom))
    canvas.paste(img_br, (x2, y2))

    _save_canvas(canvas, output_path)


# --- 5张图布局 ---

def create_collage_5_images(path_hero, path_thumb1, path_thumb2, path_thumb3, path_thumb4, output_path,
                            bg_color=(255, 255, 255)):
    """
    创建 5 张图的拼图。
    新布局：顶部一张横向主图，下方 2x2 网格（避免底部一排过长）。

    参数映射:
    - path_hero:   顶部主图（横向）
    - path_thumb1: 下方网格 左上
    - path_thumb2: 下方网格 右上
    - path_thumb3: 下方网格 左下
    - path_thumb4: 下方网格 右下
    """
    paths = [path_hero, path_thumb1, path_thumb2, path_thumb3, path_thumb4]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 5:
        print("错误：5图拼图需要5张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 顶部主图区域
    hero_w = CANVAS_WIDTH
    hero_h = 1200
    img_hero = resize_and_crop_to_fill(images[0], (hero_w, hero_h))
    canvas.paste(img_hero, (0, 0))

    # 下方 2x2 网格
    grid_y = hero_h + MARGIN
    grid_h = CANVAS_HEIGHT - hero_h - MARGIN
    cell_w = (CANVAS_WIDTH - MARGIN) // 2
    cell_h = (grid_h - MARGIN) // 2

    # 左上
    img_tl = resize_and_crop_to_fill(images[1], (cell_w, cell_h))
    canvas.paste(img_tl, (0, grid_y))
    # 右上
    img_tr = resize_and_crop_to_fill(images[2], (cell_w, cell_h))
    canvas.paste(img_tr, (cell_w + MARGIN, grid_y))
    # 左下
    img_bl = resize_and_crop_to_fill(images[3], (cell_w, cell_h))
    canvas.paste(img_bl, (0, grid_y + cell_h + MARGIN))
    # 右下
    img_br = resize_and_crop_to_fill(images[4], (cell_w, cell_h))
    canvas.paste(img_br, (cell_w + MARGIN, grid_y + cell_h + MARGIN))

    _save_canvas(canvas, output_path)


# --- 6张图布局 ---
def create_collage_6_images(path_r1c1, path_r1c2,
                            path_r2c1, path_r2c2,
                            path_r3c1, path_r3c2,
                            output_path, bg_color=(255, 255, 255)):
    """
    创建 6 张图的拼图。 (新布局)
    布局：2x3 网格 (2列 x 3行)，以获得更均衡的单元格。

    参数映射: (r=Row, c=Column)
    - path_r1c1: 第一行，左图
    - path_r1c2: 第一行，右图
    - path_r2c1: 第二行，左图
    - path_r2c2: 第二行，右图
    - path_r3c1: 第三行，左图
    - path_r3c2: 第三行，右图
    """
    paths = [path_r1c1, path_r1c2, path_r2c1, path_r2c2, path_r3c1, path_r3c2]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 6:
        print("错误：6图拼图需要6张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 2列 x 3行，仅保留内部间距
    cell_w = (CANVAS_WIDTH - MARGIN) // 2
    cell_h = (CANVAS_HEIGHT - 2 * MARGIN) // 3

    img_index = 0
    for r in range(3):  # 3 行
        for c in range(2):  # 2 列
            x = c * (cell_w + MARGIN)
            y = r * (cell_h + MARGIN)
            img_cell = resize_and_crop_to_fill(images[img_index], (cell_w, cell_h))
            canvas.paste(img_cell, (x, y))
            img_index += 1

    _save_canvas(canvas, output_path)


# --- 7张图布局 ---

def create_collage_7_images(path_hero, path_t1, path_t2, path_t3, path_b1, path_b2, path_b3, output_path,
                            bg_color=(255, 255, 255)):
    """
    创建 7 张图的拼图。
    布局：中间一张横向主图，上下各一排 3 张缩略图。

    参数映射:
    - path_hero: 中间的主图
    - path_t1:   顶部左图
    - path_t2:   顶部中图
    - path_t3:   顶部右图
    - path_b1:   底部左图
    - path_b2:   底部中图
    - path_b3:   底部右图
    """
    paths = [path_hero, path_t1, path_t2, path_t3, path_b1, path_b2, path_b3]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 7:
        print("错误：7图拼图需要7张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    hero_h = 1000
    thumb_h = (CANVAS_HEIGHT - 2 * MARGIN - hero_h) // 2
    thumb_w = (CANVAS_WIDTH - 2 * MARGIN) // 3

    # 顶部缩略图
    y_top = 0
    for i in range(3):
        x = i * (thumb_w + MARGIN)
        img_cell = resize_and_crop_to_fill(images[i + 1], (thumb_w, thumb_h))
        canvas.paste(img_cell, (x, y_top))

    # 中间主图
    y_hero = thumb_h + MARGIN
    hero_w = CANVAS_WIDTH
    img_hero = resize_and_crop_to_fill(images[0], (hero_w, hero_h))
    canvas.paste(img_hero, (0, y_hero))

    # 底部缩略图
    y_bottom = y_hero + hero_h + MARGIN
    for i in range(3):
        x = i * (thumb_w + MARGIN)
        img_cell = resize_and_crop_to_fill(images[i + 4], (thumb_w, thumb_h))
        canvas.paste(img_cell, (x, y_bottom))

    _save_canvas(canvas, output_path)


# --- 8张图布局 (新版：3-2-3 布局) ---

def create_collage_8_images(path_t1, path_t2, path_t3,
                            path_m1, path_m2,
                            path_b1, path_b2, path_b3,
                            output_path, bg_color=(255, 255, 255)):
    """
    创建 8 张图的拼图。 (新布局)
    布局：3-2-3 垂直堆叠。中间两张图更突出。

    参数映射:
    - path_t1, path_t2, path_t3: 顶部第一行 (3张)
    - path_m1, path_m2:         中间第二行 (2张, 突出显示)
    - path_b1, path_b2, path_b3: 底部第三行 (3张)
    """
    paths = [path_t1, path_t2, path_t3, path_m1, path_m2, path_b1, path_b2, path_b3]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 8:
        print("错误：8图拼图需要8张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 1. 计算高度（仅保留内部竖向间距）
    h_mid = 800
    h_side = (CANVAS_HEIGHT - h_mid - 2 * MARGIN) // 2

    # 2. 计算宽度（仅保留内部横向间距）
    w_3_cell = (CANVAS_WIDTH - 2 * MARGIN) // 3
    w_2_cell = (CANVAS_WIDTH - MARGIN) // 2

    # --- 绘制 第1行 (顶部, 3张) ---
    y_top = 0
    img_index = 0
    for c in range(3):
        x = c * (w_3_cell + MARGIN)
        img_cell = resize_and_crop_to_fill(images[img_index], (w_3_cell, h_side))
        canvas.paste(img_cell, (x, y_top))
        img_index += 1  # 0, 1, 2

    # --- 绘制 第2行 (中间, 2张) ---
    y_mid = h_side + MARGIN
    for c in range(2):
        x = c * (w_2_cell + MARGIN)
        img_cell = resize_and_crop_to_fill(images[img_index], (w_2_cell, h_mid))
        canvas.paste(img_cell, (x, y_mid))
        img_index += 1  # 3, 4

    # --- 绘制 第3行 (底部, 3张) ---
    y_bottom = y_mid + h_mid + MARGIN
    for c in range(3):
        x = c * (w_3_cell + MARGIN)
        img_cell = resize_and_crop_to_fill(images[img_index], (w_3_cell, h_side))
        canvas.paste(img_cell, (x, y_bottom))
        img_index += 1  # 5, 6, 7

    _save_canvas(canvas, output_path)


# --- 9张图布局 ---

def create_collage_9_images_1_and_4x4(path_hero, path_g1, path_g2, path_g3, path_g4, path_g5, path_g6, path_g7, path_g8,
                                      output_path, bg_color=(255, 255, 255)):
    """
    创建 9 张图的拼图。
    原布局：顶部主图 + 底部 4x2 网格。

    参数保持兼容：path_hero 作为顶部主图，path_g1~path_g8 依序填充底部 4x2。
    """
    paths = [path_hero, path_g1, path_g2, path_g3, path_g4,
             path_g5, path_g6, path_g7, path_g8]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 9:
        print("错误：9图拼图需要9张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 1
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 顶部主图区域
    hero_w = CANVAS_WIDTH
    hero_h = 1100
    hero_img = resize_and_crop_to_fill(images[0], (hero_w, hero_h))
    canvas.paste(hero_img, (0, 0))

    # 底部 4x2 网格区域
    grid_top_y = hero_h
    grid_height = CANVAS_HEIGHT - grid_top_y
    cols, rows = 4, 2
    # 横向仅内部3个间距；纵向包含 与主图之间1个间距 + 行间1个间距
    cell_w = (CANVAS_WIDTH - (cols - 1) * MARGIN) // cols
    cell_h = (CANVAS_HEIGHT - hero_h - rows * MARGIN) // rows

    img_index = 1
    for r in range(rows):
        for c in range(cols):
            x = c * (cell_w + MARGIN)
            y = grid_top_y + MARGIN + r * (cell_h + MARGIN)
            img_cell = resize_and_crop_to_fill(images[img_index], (cell_w, cell_h))
            canvas.paste(img_cell, (x, y))
            img_index += 1

    _save_canvas(canvas, output_path)


def create_collage_9_images_3x3(path_r1c1, path_r1c2, path_r1c3,
                                path_r2c1, path_r2c2, path_r2c3,
                                path_r3c1, path_r3c2, path_r3c3,
                                output_path, bg_color=(255, 255, 255)):
    """
    新增布局：标准 3x3 九宫格（全部等大小，无主次）。
    参数使用 r{row}c{col} 语义，便于理解位置。
    """
    paths = [
        path_r1c1, path_r1c2, path_r1c3,
        path_r2c1, path_r2c2, path_r2c3,
        path_r3c1, path_r3c2, path_r3c3,
    ]
    images, loaded = _load_images(paths)
    if not loaded or len(images) != 9:
        print("错误：9图拼图需要9张有效的图片。")
        return

    CANVAS_WIDTH = 1800
    CANVAS_HEIGHT = 2400
    MARGIN = 0
    canvas = Image.new('RGB', (CANVAS_WIDTH, CANVAS_HEIGHT), bg_color)

    # 3列仅有2个内部间距；3行仅有2个内部间距
    cell_w = (CANVAS_WIDTH - 2 * MARGIN) // 3
    cell_h = (CANVAS_HEIGHT - 2 * MARGIN) // 3

    img_index = 0
    for r in range(3):
        for c in range(3):
            x = c * (cell_w + MARGIN)
            y = r * (cell_h + MARGIN)
            img_cell = resize_and_crop_to_fill(images[img_index], (cell_w, cell_h))
            canvas.paste(img_cell, (x, y))
            img_index += 1

    _save_canvas(canvas, output_path)


# ----------------------------------------------------------------------------


def generate_layout_map() -> dict:
    """
    通过 Python 的 'inspect' 模块自动扫描 collage_scheme.py 文件，
    提取所有 create_collage_..._images 函数，并生成 JSON map。
    """
    print(f"--- 正在从 {MODULE_NAME}.py 扫描布局函数 ---")

    try:
        # 直接引用当前模块对象
        module = sys.modules[__name__]
    except Exception as e:
        print(f"❌ 错误：无法获取当前模块 '{MODULE_NAME}'。")
        print(f"当前搜索路径: {sys.path}")
        print(f"当前工作目录: {os.getcwd()}")
        print(f"脚本所在目录: {os.path.dirname(os.path.abspath(__file__))}")
        print(f"导入错误详情: {e}")
        return {}

    layout_map = []

    # 遍历模块中所有成员
    for name, func in inspect.getmembers(module, inspect.isfunction):
        # 筛选出我们需要的函数
        if name.startswith("create_collage_"):
            try:
                sig = inspect.signature(func)
                doc = inspect.getdoc(func)

                # 1. 获取参数, 排除 'output_path' 和 'bg_color'
                params = sig.parameters
                param_example = {}
                image_params = []

                for param_name, param in params.items():
                    # 假设所有非 "output" 或 "bg" 的参数都是图片路径
                    if param_name not in ["output_path", "bg_color"]:
                        param_example[param_name] = "string (图片路径)"
                        image_params.append(param_name)

                # 2. 获取图片数量
                image_count = len(image_params)
                if image_count == 0:
                    continue  # 跳过辅助函数

                # 3. 获取描述 (使用完整的 docstring)
                description = "No description found."
                if doc:
                    description = doc.strip()

                function_data = {
                    "function_name": name,
                    "image_count": image_count,
                    "description": description,
                    "parameter_example": param_example
                }
                layout_map.append(function_data)
                print(f"  [+] 找到: {name} ({image_count} 张图)")

            except Exception as e:
                print(f"  [!] 处理函数 {name} 时出错: {e}")

    # 4. 按图片数量排序
    layout_map.sort(key=lambda x: x['image_count'])

    print(f"✅ 成功扫描到 {len(layout_map)} 个布局函数")
    return layout_map

# if __name__ == "__main__":
#     result = generate_layout_map()
#     print(f"生成的布局映射: {json.dumps(result, indent=2, ensure_ascii=False)}")
#
#
#
# if __name__ == "__main__":
#
#     import glob  # 确保导入 glob
#
#     test_img_dir = os.path.join('..', 'data', '2025-11-01', '1')  # 假设脚本在'src'下
#     # 注意：请根据您的实际文件结构调整此路径
#     # 例如： "..\\..\\data\\2025-11-01\\1" (Windows)
#
#     # 1. 定义您的图片文件夹路径
#     # 从src/test目录到项目根目录需要回退两级，然后进入data目录
#     test_img_dir = "..\\..\\data\\2025-11-01\\1"
#
#     print(f"正在从文件夹搜索图片: {os.path.abspath(test_img_dir)}")
#
#     # 检查目录是否存在
#     if not os.path.exists(test_img_dir):
#         print(f"❌ 错误：目录不存在: {os.path.abspath(test_img_dir)}")
#         print("🔍 正在检查可能的替代路径...")
#
#         # 检查一些可能的路径
#         possible_paths = [
#             "data\\2025-11-01\\1",
#             "..\\data\\2025-11-01\\1",
#             "..\\..\\data\\2025-11-01\\1",
#             "data\\2025-11-01\\1.mp4",
#             "..\\data\\2025-11-01\\1.mp4"
#         ]
#
#     supported_extensions = ('*.jpg', '*.jpeg', '*.png', '*.JPG', '*.PNG')
#     image_paths = []
#     print(f"🔍 正在搜索图片... (在: {os.path.abspath(test_img_dir)})")
#     for ext in supported_extensions:
#         pattern = os.path.join(test_img_dir, ext)
#         matches = glob.glob(pattern)
#         if matches:
#             print(f"   找到 {len(matches)} 个 {ext} 文件")
#         image_paths.extend(matches)
#
#     # 按文件名排序，确保每次运行结果一致
#     image_paths.sort()
#     total_images = len(image_paths)
#     print(f"📊 总共找到 {total_images} 张图片")
#
#     # 4. 准备输出目录
#     output_dir = "collage_results_test_03"
#     os.makedirs(output_dir, exist_ok=True)
#     print(f"🚀 拼图结果将保存到: {os.path.abspath(output_dir)}")
#
#     # 5. 动态调用拼图函数
#
#     # 为了方便, 将路径列表赋值给 p
#     # 这样我们可以用 p[0], p[1] 来引用图片
#     p = image_paths
#
#     print("\n--- 开始按顺序生成拼图 ---")
#     if total_images >= 1:
#         print("正在测试: 2图布局 (上/下)")
#         create_collage_1_images(
#             path_main=p[0],
#             output_path=os.path.join(output_dir, "collage_1_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 2图布局 (图片不足)")
#     # --- 2 图测试 ---
#     if total_images >= 2:
#         print("正在测试: 2图布局 (上/下)")
#         create_collage_2_images(
#             path_top=p[0],
#             path_bottom=p[1],
#             output_path=os.path.join(output_dir, "collage_2_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 2图布局 (图片不足)")
#
#     # --- 3 图测试 ---
#     if total_images >= 3:
#         print("正在测试: 3图布局 (顶部主图 + 底部并排)")
#         create_collage_3_images(
#             path_top_hero=p[0],
#             path_bottom_left=p[1],
#             path_bottom_right=p[2],
#             output_path=os.path.join(output_dir, "collage_3_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 3图布局 (图片不足)")
#
#     # --- 4 图测试 ---
#     if total_images >= 4:
#         print("正在测试: 4图布局 (田字格)")
#         create_collage_4_images(
#             path_tl=p[0], path_tr=p[1],
#             path_bl=p[2], path_br=p[3],
#             output_path=os.path.join(output_dir, "collage_4_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 4图布局 (图片不足)")
#
#     # --- 5 图测试 ---
#     if total_images >= 5:
#         print("正在测试: 5图布局 (顶部主图 + 下方2x2)")
#         create_collage_5_images(
#             path_hero=p[0],
#             path_thumb1=p[1], path_thumb2=p[2],
#             path_thumb3=p[3], path_thumb4=p[4],
#             output_path=os.path.join(output_dir, "collage_5_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 5图布局 (图片不足)")
#
#     # --- 6 图测试 ---
#     if total_images >= 6:
#         print("正在测试: 6图布局 (新 2x3 网格)")
#         create_collage_6_images(
#             path_r1c1=p[0], path_r1c2=p[1],  # 第 1 行
#             path_r2c1=p[2], path_r2c2=p[3],  # 第 2 行
#             path_r3c1=p[4], path_r3c2=p[5],  # 第 3 行
#             output_path=os.path.join(output_dir, "collage_6_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 6图布局 (图片不足)")
#
#     # --- 7 图测试 ---
#     if total_images >= 7:
#         print("正在测试: 7图布局 (中/上/下)")
#         create_collage_7_images(
#             path_hero=p[0],
#             path_t1=p[1], path_t2=p[2], path_t3=p[3],
#             path_b1=p[4], path_b2=p[5], path_b3=p[6],
#             output_path=os.path.join(output_dir, "collage_7_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 7图布局 (图片不足)")
#
#     # --- 8 图测试 ---
#     if total_images >= 8:
#         print("正在测试: 8图布局 (新 3-2-3 布局)")
#         create_collage_8_images(
#             path_t1=p[0], path_t2=p[1], path_t3=p[2],  # 顶部3张
#             path_m1=p[3], path_m2=p[4],  # 中间2张 (突出)
#             path_b1=p[5], path_b2=p[6], path_b3=p[7],  # 底部3张
#             output_path=os.path.join(output_dir, "collage_8_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 8图布局 (图片不足)")
#
#     # --- 9 图测试 ---
#     if total_images >= 9:
#         print("正在测试: 9图布局 (原 顶部主图 + 下方4x2)")
#         create_collage_9_images_1_and_4x4(
#             path_hero=p[0],
#             path_g1=p[1], path_g2=p[2], path_g3=p[3], path_g4=p[4],
#             path_g5=p[5], path_g6=p[6], path_g7=p[7], path_g8=p[8],
#             output_path=os.path.join(output_dir, "collage_9_hero_grid_output.jpg")
#         )
#
#         print("正在测试: 9图布局 (3x3 九宫格)")
#         create_collage_9_images_3x3(
#             path_r1c1=p[0], path_r1c2=p[1], path_r1c3=p[2],
#             path_r2c1=p[3], path_r2c2=p[4], path_r2c3=p[5],
#             path_r3c1=p[6], path_r3c2=p[7], path_r3c3=p[8],
#             output_path=os.path.join(output_dir, "collage_9_3x3_output.jpg")
#         )
#     else:
#         print("⚠️ 跳过 9图布局 (图片不足)")
#
#     print(f"\n🎉 所有可执行的拼图已生成！请查看 '{output_dir}' 文件夹。")
