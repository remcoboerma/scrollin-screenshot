import sys
import subprocess
import time
import pyautogui
from mss import mss
from PyQt5 import QtWidgets, QtCore, QtGui
import numpy as np
from PIL import Image

# --- Selection overlay (like Flameshot) using PyQt5 ---
class RectSelector(QtWidgets.QWidget):
    rect_selected = QtCore.pyqtSignal(int, int, int, int)

    def __init__(self):
        super().__init__()
        self.begin = QtCore.QPoint()
        self.end = QtCore.QPoint()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowOpacity(0.3)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.showFullScreen()

    def mousePressEvent(self, event):
        self.begin = event.pos()
        self.end = event.pos()
        self.update()

    def mouseMoveEvent(self, event):
        self.end = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        x1 = min(self.begin.x(), self.end.x())
        y1 = min(self.begin.y(), self.end.y())
        x2 = max(self.begin.x(), self.end.x())
        y2 = max(self.begin.y(), self.end.y())
        self.rect_selected.emit(x1, y1, x2-x1, y2-y1)
        self.hide()

    def paintEvent(self, event):
        qp = QtGui.QPainter(self)
        qp.setPen(QtGui.QPen(QtCore.Qt.red, 2))
        qp.drawRect(QtCore.QRect(self.begin, self.end))


# --- Window selection using Tkinter ---
import tkinter as tk
from tkinter import ttk

def list_windows():
    print("Listing available windows...")
    out = subprocess.check_output(['wmctrl', '-l']).decode()
    windows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            windows.append({'id': parts[0], 'title': parts[3]})
    print(f"Found {len(windows)} windows")
    return windows

def select_window():
    win_root = tk.Tk()
    win_root.title("Select Window")
    wins = list_windows()
    titles = [w['title'] for w in wins]
    var = tk.StringVar()
    label = tk.Label(win_root, text="Choose window to control:")
    label.pack()
    combo = ttk.Combobox(win_root, textvariable=var, values=titles, width=70, state="readonly")
    combo.pack(pady=10)
    selected = {'index': None}
    
    def on_sel(event):
        selected['index'] = combo.current()
        
    def on_start():
        if selected['index'] is not None:
            win_root.destroy()
        else:
            tk.Label(win_root, text="Please select a window", fg="red").pack()
            
    combo.bind('<<ComboboxSelected>>', on_sel)
    start_btn = tk.Button(win_root, text="Start", command=on_start)
    start_btn.pack(pady=10)
    win_root.mainloop()
    return wins[selected['index']] if selected['index'] is not None else None

def focus_window(win_id):
    # Use wmctrl to focus, waits a short moment after
    print(f"Focusing window with ID: {win_id}")
    subprocess.run(['wmctrl', '-ia', win_id])
    time.sleep(0.5)

def capture_region(region, filename):
    # region: (left, top, width, height)
    with mss() as sct:
        sct_img = sct.grab({
            "top": region[1],
            "left": region[0],
            "width": region[2],
            "height": region[3]
        })
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        img.save(filename)
    return np.array(img)

def find_overlap_and_stitch(im1, im2):
    ''' 
    im1, im2: numpy arrays (H,W,C) 
    Returns stitched image (im1 on top, im2 cropped so only new region added).
    '''
    overlap_min = 50  # Minimum presumed overlap height (in pixels)
    max_overlap = min(im1.shape[0], im2.shape[0], 500)  # Maximum overlap trackable
    best_offset, min_diff = 0, float('inf')
    for overlap in range(overlap_min, max_overlap):
        a = im1[-overlap:, :, :]
        b = im2[:overlap, :, :]
        diff = np.sum(np.abs(a.astype(int) - b.astype(int)))
        if diff < min_diff:
            min_diff = diff
            best_offset = overlap
    # Optionally check if the match is 'good enough'
    stitched = np.vstack([im1, im2[best_offset:]])
    return stitched

def save_np_image(arr, filename):
    img = Image.fromarray(arr.astype('uint8'))
    img.save(filename)

def main():
    print("Starting main function...")
    # 1. Select window
    print("Step 1: Selecting window...")
    win = select_window()
    if not win:
        print("ERROR: No window selected.")
        sys.exit(1)
    win_id = win['id']
    print(f"Selected window: {win['title']} (ID: {win_id})")

    # 2. Select rectangle
    print("Step 2: Starting region selection...")
    app = QtWidgets.QApplication(sys.argv)
    print("Created QApplication")
    selector = RectSelector()
    print("Created RectSelector widget")
    # shared state for communication between PyQt and main
    rect = {}
    def on_rect_selected(x, y, w, h):
        print(f"Rectangle selected: x={x}, y={y}, w={w}, h={h}")
        rect['region'] = (x, y, w, h)
        app.quit()
    selector.rect_selected.connect(on_rect_selected)
    print("Starting region selection interface...")
    app.exec_()
    region = rect['region']
    print(f"Selected region: {region}")

    # 3. Focus window and capture first screenshot
    print("Step 3: Focusing window and taking first screenshot...")
    focus_window(win_id)
    print("Window focused")
    time.sleep(0.2)  # Give some settle time
    print("Taking first screenshot...")
    img1 = capture_region(region, "capture1.png")
    print("First screenshot taken (capture1.png)")

    # 4. Send pagedown
    print("Step 4: Sending PageDown key...")
    focus_window(win_id)
    print("Window re-focused")
    time.sleep(0.1)
    pyautogui.press('pagedown')
    print("PageDown pressed.")
    time.sleep(0.5)
    print("Waiting for scroll to complete...")

    # 5. Capture second screenshot
    print("Step 5: Taking second screenshot...")
    img2 = capture_region(region, "capture2.png")
    print("Second screenshot taken (capture2.png)")

    # 6. Stitch images (remove overlap)
    print("Step 6: Stitching images...")
    print(f"Image 1 shape: {img1.shape}")
    print(f"Image 2 shape: {img2.shape}")
    stitched = find_overlap_and_stitch(img1, img2)
    print(f"Stitched image shape: {stitched.shape}")
    save_np_image(stitched, "stitched.png")
    print("Stitched image saved as stitched.png.")
    print("Process completed successfully!")


if __name__ == "__main__":
    main()
