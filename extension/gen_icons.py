"""生成扩展图标（纯色带箭头的简单 PNG）"""
import struct
import zlib

def create_png(size):
    """生成一个简单的下载箭头图标 PNG"""
    pixels = []
    center = size // 2
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - center, y - center
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < size * 0.45:
                arrow_w = size // 5
                shaft_top = -size // 4
                shaft_bot = size // 10
                head_top = shaft_bot
                head_bot = size // 3
                head_w = size // 3
                in_shaft = shaft_top <= dy <= shaft_bot and abs(dx) <= arrow_w // 2
                in_head = head_top <= dy <= head_bot and abs(dx) <= head_w * (head_bot - dy) / (head_bot - head_top)
                bar_y = size // 3 + 2
                in_bar = bar_y <= dy <= bar_y + max(size // 16, 2) and abs(dx) <= size // 3
                if in_shaft or in_head or in_bar:
                    row.extend([255, 255, 255, 255])
                else:
                    row.extend([15, 125, 255, 255])
            else:
                row.extend([0, 0, 0, 0])
        pixels.append(bytes([0] + row))

    raw = b''.join(pixels)
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', ihdr) +
            chunk(b'IDAT', zlib.compress(raw)) +
            chunk(b'IEND', b''))

for s in [16, 48, 128]:
    with open(f'icons/icon{s}.png', 'wb') as f:
        f.write(create_png(s))
    print(f'icons/icon{s}.png generated')
