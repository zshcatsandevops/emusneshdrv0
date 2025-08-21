# snes_gui.py
# ZSNES-style frontend + SNES emulator backend (single file demo)
# Author: ChatGPT

import tkinter as tk
from tkinter import filedialog, messagebox
import threading, time, os, sys
import numpy as np
from PIL import Image, ImageTk

# -----------------------------
# Backend: SNES Emulator Core
# -----------------------------
SCREEN_WIDTH, SCREEN_HEIGHT = 256, 224
FPS = 60

class Memory:
    def __init__(self):
        self.ram = bytearray(128 * 1024)
        self.rom = bytearray()
        self.rom_size = 0

    def load_rom(self, path):
        with open(path, "rb") as f:
            self.rom = f.read()
        self.rom_size = len(self.rom)
        return True

    def read8(self, addr):
        if addr < 0x2000:
            return self.ram[addr % len(self.ram)]
        elif 0x8000 <= addr <= 0xFFFF:
            off = addr - 0x8000
            if off < self.rom_size:
                return self.rom[off]
            return 0
        return 0

    def write8(self, addr, val):
        if addr < 0x2000:
            self.ram[addr % len(self.ram)] = val & 0xFF


class CPU65816:
    def __init__(self, mem):
        self.mem = mem
        self.pc = 0x8000
        self.a = 0
        self.sp = 0x1FF
        self.p = 0x34
        self.cycles = 0

    def step(self):
        op = self.mem.read8(self.pc)
        self.pc += 1
        if op == 0xEA:  # NOP
            self.cycles += 2
        elif op == 0xA9:  # LDA #imm
            val = self.mem.read8(self.pc)
            self.pc += 1
            self.a = val
            self.cycles += 2
        elif op == 0x00:  # BRK
            raise Exception("BRK instruction hit")
        else:
            self.cycles += 2


class PPU:
    def __init__(self):
        self.framebuffer = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH, 3), dtype=np.uint8)

    def render_frame(self, framecount=0):
        for y in range(SCREEN_HEIGHT):
            for x in range(SCREEN_WIDTH):
                c = (x ^ y ^ framecount) & 0xFF
                self.framebuffer[y, x] = (c, 255-c, (c//2))
        return self.framebuffer


class Joypad:
    def __init__(self):
        self.state = 0

    def set_state(self, state_bits):
        self.state = state_bits


class EmuSNES:
    def __init__(self):
        self.mem = Memory()
        self.cpu = CPU65816(self.mem)
        self.ppu = PPU()
        self.joypad = Joypad()
        self.loaded = False
        self.framecount = 0

    def load_rom(self, path):
        ok = self.mem.load_rom(path)
        self.loaded = ok
        return ok

    def reset(self):
        self.cpu.pc = 0x8000
        self.framecount = 0

    def run_frame(self):
        if not self.loaded:
            return None
        try:
            for _ in range(100):
                self.cpu.step()
        except Exception as e:
            print("CPU exception:", e)
        fb = self.ppu.render_frame(self.framecount)
        self.framecount += 1
        return fb

    def set_input(self, state_bits):
        self.joypad.set_state(state_bits)


# -----------------------------
# Frontend: ZSNES-style GUI
# -----------------------------
BG_COLOR = "#202040"
FG_COLOR = "#C0C0C0"

class ZSNESGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ZSNES (Python Edition)")
        self.root.geometry("800x600")
        self.root.configure(bg=BG_COLOR)

        # backend
        self.emu = EmuSNES()

        # menu bar
        menubar = tk.Menu(self.root, bg=BG_COLOR, fg=FG_COLOR, tearoff=0)
        self.root.config(menu=menubar)

        game_menu = tk.Menu(menubar, tearoff=0, bg=BG_COLOR, fg=FG_COLOR)
        game_menu.add_command(label="Load ROM", command=self.load_rom)
        game_menu.add_command(label="Reset", command=self.reset_rom)
        game_menu.add_separator()
        game_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="Game", menu=game_menu)

        cfg_menu = tk.Menu(menubar, tearoff=0, bg=BG_COLOR, fg=FG_COLOR)
        cfg_menu.add_command(label="Video...", command=lambda:self.show_msg("Video Settings"))
        cfg_menu.add_command(label="Sound...", command=lambda:self.show_msg("Sound Settings"))
        cfg_menu.add_command(label="Input...", command=lambda:self.show_msg("Input Settings"))
        menubar.add_cascade(label="Config", menu=cfg_menu)

        menubar.add_cascade(label="Cheat", menu=tk.Menu(menubar, tearoff=0))
        menubar.add_cascade(label="Netplay", menu=tk.Menu(menubar, tearoff=0))
        menubar.add_cascade(label="Misc", menu=tk.Menu(menubar, tearoff=0))

        help_menu = tk.Menu(menubar, tearoff=0, bg=BG_COLOR, fg=FG_COLOR)
        help_menu.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=help_menu)

        # canvas for framebuffer
        self.canvas = tk.Label(self.root, bg="black")
        self.canvas.pack(pady=10)

        # status bar
        self.status = tk.Label(self.root, text="No ROM loaded", anchor="w",
                               bg=BG_COLOR, fg=FG_COLOR, font=("Consolas", 10))
        self.status.pack(fill="x", side="bottom")

        # emulation thread
        self.running = False
        self.rom_path = None

        # key bindings
        self.root.bind("<KeyPress>", self.key_down)
        self.root.bind("<KeyRelease>", self.key_up)
        self.joy_state = 0

    def show_msg(self, txt):
        messagebox.showinfo("ZSNES", f"{txt} not implemented yet")

    def load_rom(self):
        path = filedialog.askopenfilename(filetypes=[("SNES ROMs", "*.smc *.sfc")])
        if not path: return
        if self.emu.load_rom(path):
            self.rom_path = path
            self.status.config(text=f"Loaded ROM: {os.path.basename(path)}")
            self.start_emulator()

    def start_emulator(self):
        if self.running: return
        self.running = True
        t = threading.Thread(target=self.emu_loop, daemon=True)
        t.start()

    def emu_loop(self):
        while self.running:
            fb = self.emu.run_frame()
            if fb is not None:
                img = Image.fromarray(fb, "RGB").resize((512,448))
                tk_img = ImageTk.PhotoImage(img)
                self.canvas.configure(image=tk_img)
                self.canvas.image = tk_img
                self.status.config(text=f"Running {os.path.basename(self.rom_path)} @ {FPS} FPS")
            time.sleep(1.0/FPS)

    def reset_rom(self):
        self.emu.reset()
        if self.rom_path:
            self.status.config(text=f"ROM reset: {os.path.basename(self.rom_path)}")

    def quit(self):
        self.running = False
        self.root.quit()

    def about(self):
        messagebox.showinfo("About", "ZSNES-style Emulator GUI\nPython/Tkinter Edition\n(Not official ZSNES)")

    def key_down(self, event):
        keymap = {
            "z": 1, "x": 2, "a": 4, "s": 8,
            "Return": 16, "Shift_R": 32,
            "Up": 64, "Down": 128, "Left": 256, "Right": 512
        }
        if event.keysym in keymap:
            self.joy_state |= keymap[event.keysym]
            self.emu.set_input(self.joy_state)

    def key_up(self, event):
        keymap = {
            "z": 1, "x": 2, "a": 4, "s": 8,
            "Return": 16, "Shift_R": 32,
            "Up": 64, "Down": 128, "Left": 256, "Right": 512
        }
        if event.keysym in keymap:
            self.joy_state &= ~keymap[event.keysym]
            self.emu.set_input(self.joy_state)


# -----------------------------
# Entry
# -----------------------------
if __name__ == "__main__":
    root = tk.Tk()
    gui = ZSNESGUI(root)
    root.mainloop()
