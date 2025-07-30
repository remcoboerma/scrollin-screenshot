import sys
import subprocess
import time
import pyautogui
from mss import mss
from PyQt5 import QtWidgets, QtCore, QtGui
import numpy as np
from PIL import Image
import os

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

def images_are_similar(img1, img2, threshold=5):
    """
    Compare two images to see if they're similar (indicating no new content)
    Returns True if images are similar, False otherwise
    """
    if img1.shape != img2.shape:
        return False
        
    diff = np.sum(np.abs(img1.astype(int) - img2.astype(int)))
    normalized_diff = diff / (img1.shape[0] * img1.shape[1] * img1.shape[2])
    return normalized_diff < threshold

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
    print("Please select the region you want to capture on the screen...")
    time.sleep(1)  # Give user time to see the message
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
    current_image = capture_region(region, "capture1.png")
    print("First screenshot taken (capture1.png)")
    
    # Initialize stitched image with the first capture
    stitched_image = current_image
    save_np_image(stitched_image, "stitched.png")
    iteration = 1
    temp_files = ["capture1.png"]

    # 4. Continue scrolling and capturing until no new content
    while True:
        print(f"Step {4 + iteration}: Sending PageDown key...")
        focus_window(win_id)
        print("Window re-focused")
        time.sleep(0.1)
        pyautogui.press('pagedown')
        print("PageDown pressed.")
        time.sleep(0.5)  # Wait for scroll to complete
        
        # 5. Capture screenshot
        print(f"Step {5 + iteration}: Taking screenshot...")
        filename = f"capture{iteration + 1}.png"
        new_image = capture_region(region, filename)
        temp_files.append(filename)
        print(f"Screenshot {iteration + 1} taken ({filename})")
        
        # 6. Check if new content was captured
        if images_are_similar(current_image, new_image):
            print("No new content detected. Stopping capture.")
            # Remove the last capture file since it's not needed
            if os.path.exists(filename):
                os.remove(filename)
                print(f"Removed temporary file: {filename}")
            break
            
        # 7. Stitch images (remove overlap)
        print(f"Step {6 + iteration}: Stitching new content...")
        print(f"Current stitched image shape: {stitched_image.shape}")
        print(f"New image shape: {new_image.shape}")
        stitched_image = find_overlap_and_stitch(stitched_image, new_image)
        print(f"Updated stitched image shape: {stitched_image.shape}")
        save_np_image(stitched_image, "stitched.png")
        print("Stitched image updated.")
        
        # Update current image for next comparison
        current_image = new_image
        iteration += 1
        
        # Safety check to prevent infinite loops
        if iteration > 50:
            print("Maximum iterations reached. Stopping capture.")
            break

    # Clean up temporary files
    print("Cleaning up temporary files...")
    for temp_file in temp_files:
        if os.path.exists(temp_file):
            os.remove(temp_file)
            print(f"Removed temporary file: {temp_file}")
    
    print("Process completed successfully! Final stitched image saved as stitched.png")


if __name__ == "__main__":
    main()
