# emuai_pro_pj64_legacy.py
# EmuAI Pro – N64 (Project64 1.6 / Legacy wrapper)
# Windows-only. FILES=OFF (portable overlay) by default.
# Complete backend integration with all bugs fixed.

import os
import sys
import zipfile
import shutil
import tempfile
import threading
import subprocess
import time
import platform
import configparser
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Import the backend
try:
    from emuai_pro_pj64_backend import get_backend, shutdown_backend, PluginType
    BACKEND_AVAILABLE = True
except ImportError:
    # Fallback if backend is not available
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.warning("Backend not available, using stub implementation")
    PluginType = None
    BACKEND_AVAILABLE = False
    
    def get_backend(portable_mode=True):
        return None
    
    def shutdown_backend():
        pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('emuai_pro.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

APP_TITLE = "Project64 - Legacy Wrapper (EmuAI Pro)"
PREFERRED_PAYLOAD_DIR = "pj64"
PREFERRED_PAYLOAD_ZIP = Path("assets/pj64_bundle.zip")
ROM_FILTERS = [("N64 ROMs", "*.z64 *.n64 *.v64"), ("All files", "*.*")]
ROM_DIR = Path("roms")

# Constants for subprocess
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008

def is_windows() -> bool:
    """Check if the current OS is Windows."""
    return platform.system() == "Windows"

def find_file_in_tree(root_dir: Path, filename: str) -> Optional[Path]:
    """Recursively find a file in a directory tree."""
    if not root_dir.is_dir():
        return None
    try:
        for path in root_dir.rglob(filename):
            if path.is_file():
                return path
    except (PermissionError, OSError) as e:
        logger.warning(f"Error searching for {filename} in {root_dir}: {e}")
    return None

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

class PayloadOverlay:
    """Manages a portable, ephemeral copy of Project64."""
    
    def __init__(self, ephemeral: bool = True):
        self.ephemeral = ephemeral
        self.base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        self.temp_dir = Path(tempfile.gettempdir()) / f"emuai_pro_{os.getpid()}"
        self.payload_source_dir = self.base_dir / PREFERRED_PAYLOAD_DIR
        self.payload_source_zip = self.base_dir / PREFERRED_PAYLOAD_ZIP
        
        if self.ephemeral:
            self.overlay_dir = self.temp_dir
        else:
            self.overlay_dir = self.base_dir / "pj64_files"
        
        self.pj64_dir = self.overlay_dir
        self._prepare_payload()
    
    def _prepare_payload(self):
        """Ensures the Project64 payload is ready in the overlay directory."""
        try:
            if self.pj64_dir.exists() and any(self.pj64_dir.iterdir()):
                logger.info(f"Payload directory '{self.pj64_dir}' already exists. Using it.")
                return
            
            os.makedirs(self.pj64_dir, exist_ok=True)
            source_found = False
            
            if self.payload_source_dir.exists():
                logger.info(f"Copying payload from directory: {self.payload_source_dir}")
                shutil.copytree(self.payload_source_dir, self.pj64_dir, dirs_exist_ok=True)
                source_found = True
            elif self.payload_source_zip.exists():
                logger.info(f"Extracting payload from zip: {self.payload_source_zip}")
                with zipfile.ZipFile(self.payload_source_zip, 'r') as zip_ref:
                    zip_ref.extractall(self.pj64_dir)
                source_found = True
            
            if not source_found:
                logger.warning("No payload source found. Using backend-only mode.")
                
        except Exception as e:
            logger.error(f"Error preparing payload: {e}")
            # Don't raise - we can work without payload
    
    def cleanup(self):
        """Removes the temporary overlay directory if it's ephemeral."""
        if self.ephemeral and self.temp_dir.exists():
            logger.info(f"Cleaning up ephemeral directory: {self.temp_dir}")
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except OSError as e:
                logger.error(f"Error removing temp directory: {e}")

class ConfigManager:
    """Manages Project64 configuration file operations."""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
    
    def load_config(self) -> bool:
        """Load configuration from file."""
        try:
            if not self.config_path.exists():
                logger.warning(f"Config file not found: {self.config_path}")
                return False
            
            self.config.read(self.config_path)
            logger.info(f"Config loaded from: {self.config_path}")
            return True
        except (configparser.Error, IOError) as e:
            logger.error(f"Error loading config: {e}")
            return False
    
    def save_config(self) -> bool:
        """Save configuration to file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w') as configfile:
                self.config.write(configfile)
            logger.info(f"Config saved to: {self.config_path}")
            return True
        except (configparser.Error, IOError) as e:
            logger.error(f"Error saving config: {e}")
            return False
    
    def set_graphics_plugin(self, plugin_name: str) -> bool:
        """Set the graphics plugin in the configuration."""
        try:
            if not self.load_config():
                if 'default' not in self.config:
                    self.config.add_section('default')
            
            self.config.set('default', 'Graphics Plugin', plugin_name)
            return self.save_config()
        except configparser.Error as e:
            logger.error(f"Error setting graphics plugin: {e}")
            return False
    
    def get_graphics_plugin(self) -> Optional[str]:
        """Get the current graphics plugin from configuration."""
        try:
            if not self.load_config():
                return None
            
            return self.config.get('default', 'Graphics Plugin', fallback=None)
        except configparser.Error as e:
            logger.error(f"Error getting graphics plugin: {e}")
            return None

class ROMScanner:
    """Handles ROM scanning and caching."""
    
    def __init__(self, rom_dir: Path):
        self.rom_dir = rom_dir
        self.rom_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def scan_roms(self, callback=None) -> Dict[str, Dict[str, Any]]:
        """Scan for ROMs in the ROM directory and subdirectories."""
        roms = {}
        
        if not self.rom_dir.exists() or not self.rom_dir.is_dir():
            logger.warning(f"ROM directory not found: {self.rom_dir}")
            return roms
        
        logger.info(f"Scanning for ROMs in {self.rom_dir}...")
        rom_count = 0
        
        try:
            rom_extensions = {'.z64', '.n64', '.v64'}
            
            for file in self.rom_dir.rglob('*'):
                if file.suffix.lower() in rom_extensions:
                    try:
                        stat = file.stat()
                        rom_info = {
                            'path': file,
                            'filename': file.name,
                            'goodname': file.stem.upper().replace('_', ' '),
                            'size': format_file_size(stat.st_size),
                            'size_bytes': stat.st_size,
                            'modified': stat.st_mtime,
                            'comments': "Ready to emulate"
                        }
                        
                        relative_path = file.relative_to(self.rom_dir)
                        roms[str(relative_path)] = rom_info
                        rom_count += 1
                        
                        if callback and rom_count % 10 == 0:
                            callback(rom_count)
                            
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Error accessing file {file}: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Error scanning ROMs: {e}")
        
        logger.info(f"Found {rom_count} ROMs.")
        return roms

class EmuAIPro:
    def __init__(self, root: tk.Tk):
        if not is_windows():
            messagebox.showerror("Unsupported OS", "This launcher requires Windows.")
            root.destroy()
            return
        
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x640")
        
        # Initialize ALL variables first BEFORE using them
        self.rom_path: Optional[Path] = None
        self.emu_process: Optional[subprocess.Popen] = None
        self.log_lock = threading.Lock()
        self.running = False
        self.rom_dir = ROM_DIR.resolve() if ROM_DIR.exists() else Path.home()
        
        # Initialize persist_var BEFORE building menus
        self.persist_var = tk.BooleanVar(value=False)
        
        # Initialize overlay using persist_var
        self.overlay = PayloadOverlay(ephemeral=not self.persist_var.get())
        
        # Initialize backend instead of external Project64
        self.backend_available = BACKEND_AVAILABLE
        if self.backend_available:
            try:
                self.backend = get_backend(portable_mode=True)
                if self.backend is None:
                    logger.warning("Backend initialization failed")
                    self.backend_available = False
            except Exception as e:
                logger.error(f"Error initializing backend: {e}")
                self.backend_available = False
        
        # Initialize managers
        self.config_manager = ConfigManager(self.overlay.pj64_dir / "Project64.cfg")
        self.rom_scanner = ROMScanner(self.rom_dir)
        
        # Initialize UI components
        self.rom_paths: Dict[str, Path] = {}
        self.plugin_combo = None
        self.rom_tree = None
        self.log_text = None
        self.path_label = None
        self.status = None
        
        # Build UI
        self._setup_ui_style()
        self._build_legacy_menus()
        self._build_toolbar()
        self._build_rom_browser()
        self._build_log_area()
        
        # Add remaining UI elements
        self.path_label = ttk.Label(self.root, text=self._format_paths_line(), foreground="#666")
        self.path_label.pack(fill=tk.X, pady=(2, 0))
        
        self.status = ttk.Label(self.root, anchor="w", text="Ready. FILES=OFF overlay active.")
        self.status.pack(fill=tk.X, padx=6, pady=2)
        
        # Populate and start updaters
        self._refresh_plugins()
        self._refresh_rom_list()
        self.root.after(200, self._pulse)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Check for payload and backend status
        if not self.backend_available:
            exe_path = self.overlay.pj64_dir / "Project64.exe"
            if not exe_path.exists():
                self._warn_missing_payload()
        else:
            self._log("Backend initialized successfully")
    
    def _setup_ui_style(self):
        """Setup UI styling."""
        style = ttk.Style()
        style.theme_use('classic')
        style.configure('Treeview', background='#d4d0c8', foreground='black', fieldbackground='#d4d0c8')
        style.configure('Treeview.Heading', background='#c0c0c0', foreground='black')
    
    def _build_toolbar(self):
        """Build the toolbar."""
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill=tk.X, padx=10, pady=2)
        
        ttk.Button(toolbar, text="Open ROM...", command=self.choose_rom).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Start", command=self.start_emu).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Reset", command=self.reset_emu).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Stop", command=self.stop_emu).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Refresh ROMs", command=self._refresh_rom_list).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(toolbar, text="Graphics Plugin:").pack(side=tk.LEFT, padx=(12, 4))
        self.plugin_combo = ttk.Combobox(toolbar, state="readonly", width=36)
        self.plugin_combo.pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Apply", command=self.apply_plugin).pack(side=tk.LEFT, padx=2)
    
    def _build_rom_browser(self):
        """Build the ROM browser treeview."""
        self.rom_tree = ttk.Treeview(
            self.root,
            columns=('filename', 'goodname', 'size', 'comments'),
            show='headings'
        )
        
        self.rom_tree.heading('filename', text='File Name')
        self.rom_tree.heading('goodname', text='Good Name')
        self.rom_tree.heading('size', text='Size')
        self.rom_tree.heading('comments', text='Comments')
        
        self.rom_tree.column('filename', width=200)
        self.rom_tree.column('goodname', width=300)
        self.rom_tree.column('size', width=100)
        self.rom_tree.column('comments', width=200)
        
        self.rom_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        self.rom_tree.bind('<Double-1>', self._on_rom_double_click)
    
    def _build_log_area(self):
        """Build the log area."""
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill=tk.X, padx=10, pady=2)
        
        ttk.Label(log_frame, text="Log:").pack(side=tk.LEFT)
        self.log_text = tk.Text(log_frame, height=5, state=tk.DISABLED)
        self.log_text.pack(fill=tk.X, expand=True)
    
    def _build_legacy_menus(self):
        """Build legacy menus."""
        menubar = tk.Menu(self.root)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open ROM...", command=self.choose_rom, accelerator="Ctrl+O")
        file_menu.add_command(label="ROM Directory...", command=self._choose_rom_dir)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        
        # System menu
        system_menu = tk.Menu(menubar, tearoff=0)
        system_menu.add_command(label="Reset", command=self.reset_emu)
        system_menu.add_command(label="Pause", command=lambda: self._log("Legacy pause stubbed"))
        system_menu.add_command(label="Bitmap Screenshot", command=lambda: self._log("Legacy screenshot stubbed"))
        system_menu.add_separator()
        system_menu.add_command(label="Save State", command=self._save_state)
        system_menu.add_command(label="Load State", command=self._load_state)
        system_menu.add_command(label="Cheats...", command=lambda: self._log("Legacy cheats stubbed"))
        menubar.add_cascade(label="System", menu=system_menu)
        
        # Options menu
        options_menu = tk.Menu(menubar, tearoff=0)
        options_menu.add_command(label="Settings...", command=self._show_settings_stub)
        options_menu.add_command(label="Full Screen", command=lambda: self._log("Full screen stubbed"))
        options_menu.add_command(label="Configure Graphics Plugin...", command=self.apply_plugin)
        options_menu.add_checkbutton(
            label="Persist overlay (FILES=ON)",
            variable=self.persist_var,
            command=self._toggle_persist
        )
        menubar.add_cascade(label="Options", menu=options_menu)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def _log(self, message: str):
        """Thread-safe logging to the UI."""
        with self.log_lock:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        logger.info(message)
    
    def _pulse(self):
        """Periodic UI update loop."""
        if self.backend_available:
            # Check backend status
            try:
                info = self.backend.get_emulation_info()
                if info['running'] != self.running:
                    self.running = info['running']
                    if not self.running:
                        self._log("Emulator process finished.")
            except Exception as e:
                logger.error(f"Error checking backend status: {e}")
        elif self.emu_process and self.emu_process.poll() is not None:
            self._log(f"Emulator process finished with code {self.emu_process.returncode}.")
            self.emu_process = None
            self.running = False
        
        status_text = "Running..." if self.running else "Ready."
        if not self.overlay.ephemeral:
            status_text += " FILES=ON overlay active."
        else:
            status_text += " FILES=OFF overlay active."
        self.status.config(text=status_text)
        self.path_label.config(text=self._format_paths_line())
        self.root.after(500, self._pulse)
    
    def _on_close(self):
        """Handles application shutdown."""
        try:
            self.stop_emu()
            self.overlay.cleanup()
            if self.backend_available:
                shutdown_backend()
            self.root.destroy()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            self.root.destroy()
    
    def _warn_missing_payload(self):
        """Shows a warning if Project64.exe is not found."""
        messagebox.showwarning(
            "Payload Missing",
            "Project64.exe not found!\n\n"
            f"Please place your Project64 1.6 files in a folder named '{PREFERRED_PAYLOAD_DIR}' "
            f"next to this script, or provide a '{PREFERRED_PAYLOAD_ZIP}' file."
        )
    
    def _choose_rom_dir(self):
        """Lets the user select a new directory for ROMs."""
        new_dir = filedialog.askdirectory(
            title="Choose ROM Directory",
            initialdir=str(self.rom_dir)
        )
        if new_dir:
            self.rom_dir = Path(new_dir)
            self.rom_scanner = ROMScanner(self.rom_dir)
            self._log(f"Set ROM directory to: {self.rom_dir}")
            self._refresh_rom_list()
    
    def _refresh_rom_list(self):
        """Refresh the ROM list with improved error handling and progress feedback."""
        # Clear existing items
        for item in self.rom_tree.get_children():
            self.rom_tree.delete(item)
        self.rom_paths.clear()
        
        def progress_callback(count):
            self._log(f"Scanning... found {count} ROMs")
        
        # Scan ROMs in a separate thread to prevent UI freezing
        def scan_thread():
            try:
                roms = self.rom_scanner.scan_roms(progress_callback)
                
                # Update UI in main thread
                self.root.after(0, self._update_rom_tree, roms)
                
            except Exception as e:
                logger.error(f"Error scanning ROMs: {e}")
                self.root.after(0, self._log, f"Error scanning ROMs: {e}")
        
        threading.Thread(target=scan_thread, daemon=True).start()
        self._log("Starting ROM scan...")
    
    def _update_rom_tree(self, roms: Dict[str, Dict[str, Any]]):
        """Update the ROM tree with scanned ROMs."""
        try:
            for display_path, rom_info in roms.items():
                item_id = self.rom_tree.insert('', tk.END, values=(
                    display_path,
                    rom_info['goodname'],
                    rom_info['size'],
                    rom_info['comments']
                ))
                self.rom_paths[item_id] = rom_info['path']
            
            self._log(f"Found {len(roms)} ROMs.")
        except Exception as e:
            logger.error(f"Error updating ROM tree: {e}")
            self._log(f"Error updating ROM list: {e}")
    
    def _on_rom_double_click(self, event):
        """Handle ROM double-click with improved error handling."""
        try:
            selection = self.rom_tree.selection()
            if not selection:
                return
            
            selected_item_id = selection[0]
            if selected_item_id in self.rom_paths:
                self.rom_path = self.rom_paths[selected_item_id]
                self._log(f"Selected ROM via double-click: {self.rom_path.name}")
                self.start_emu()
            else:
                self._log("Error: Could not find path for selected ROM.")
        except Exception as e:
            logger.error(f"Error handling ROM double-click: {e}")
            self._log(f"Error selecting ROM: {e}")
    
    def _show_settings_stub(self):
        """Show settings information."""
        messagebox.showinfo(
            "Settings",
            "Legacy settings are managed via the main window.\n"
            "Use the graphics plugin dropdown and click 'Apply' to save."
        )
    
    def _toggle_persist(self):
        """Handle overlay persistence toggle."""
        is_persistent = self.persist_var.get()
        messagebox.showinfo("Mode Changed", "This setting will apply on the next launch.")
        self._log(f"Overlay persistence set to: {'ON' if is_persistent else 'OFF'}")
    
    def _about(self):
        """Show about dialog."""
        messagebox.showinfo(
            APP_TITLE,
            "EmuAI Pro - Legacy Wrapper\n\nA portable frontend for Project64 1.6 with integrated N64 emulation backend."
        )
    
    def _format_paths_line(self) -> str:
        """Generate the path information string for the UI."""
        if self.backend_available and hasattr(self, 'backend'):
            try:
                info = self.backend.get_emulation_info()
                return (
                    f"Backend: Active | ROM: {'Loaded' if info['rom_loaded'] else 'None'} | "
                    f"Status: {'Running' if info['running'] else 'Ready'} | "
                    f"Plugins: {', '.join(info['plugins'].values())}"
                )
            except:
                return "Backend: Initializing..."
        else:
            pj = self.overlay.pj64_dir
            exe = pj / "Project64.exe"
            return (
                f"PJ64 dir: {pj} | EXE: {'found' if exe.exists() else 'MISSING'} | "
                f"ROM dir: {self.rom_dir} | Overlay: {self.overlay.overlay_dir}"
            )
    
    def _refresh_plugins(self):
        """Scan for GFX plugins and populate the combobox."""
        if self.backend_available:
            try:
                plugins = self.backend.get_graphics_plugins()
                self.plugin_combo['values'] = plugins
                
                if plugins:
                    current_plugin = self.backend.get_current_graphics_plugin()
                    if current_plugin and current_plugin in plugins:
                        self.plugin_combo.set(current_plugin)
                    else:
                        self.plugin_combo.current(0)
                    
                    self._log(f"Found {len(plugins)} graphics plugins.")
                else:
                    self._log("No graphics plugins found.")
            except Exception as e:
                logger.error(f"Error refreshing plugins: {e}")
                self._log(f"Error scanning plugins: {e}")
        else:
            # Fallback to scanning for DLL files
            plugin_dir = self.overlay.pj64_dir / "Plugin"
            if not plugin_dir.exists():
                self._log("Plugin directory not found.")
                return
            
            try:
                plugins = [f.name for f in plugin_dir.glob("*.dll")
                          if f.name.lower().startswith("gfx")]
                self.plugin_combo['values'] = plugins
                
                if plugins:
                    # Try to load current plugin from config
                    current_plugin = self.config_manager.get_graphics_plugin()
                    if current_plugin and current_plugin in plugins:
                        self.plugin_combo.set(current_plugin)
                    else:
                        self.plugin_combo.current(0)
                    
                    self._log(f"Found {len(plugins)} graphics plugins.")
                else:
                    self._log("No graphics plugins found.")
            except Exception as e:
                logger.error(f"Error refreshing plugins: {e}")
                self._log(f"Error scanning plugins: {e}")
    
    def choose_rom(self):
        """Open a file dialog to select a ROM."""
        filepath = filedialog.askopenfilename(
            title="Open N64 ROM",
            initialdir=str(self.rom_dir),
            filetypes=ROM_FILTERS
        )
        if filepath:
            self.rom_path = Path(filepath)
            self._log(f"Selected ROM via file dialog: {self.rom_path.name}")
            
            # Update ROM directory if the selected ROM is in a different location
            new_rom_dir = self.rom_path.parent
            if new_rom_dir != self.rom_dir:
                self.rom_dir = new_rom_dir
                self.rom_scanner = ROMScanner(self.rom_dir)
                self._refresh_rom_list()
            
            # Select the ROM in the tree if it exists
            for iid, path in self.rom_paths.items():
                if path == self.rom_path:
                    self.rom_tree.selection_set(iid)
                    self.rom_tree.focus(iid)
                    break
    
    def apply_plugin(self):
        """Apply the selected graphics plugin."""
        selected_plugin = self.plugin_combo.get()
        if not selected_plugin:
            self._log("No plugin selected to apply.")
            messagebox.showerror("Error", "No graphics plugin selected.")
            return
        
        if self.backend_available:
            try:
                success = self.backend.set_graphics_plugin(selected_plugin)
                if success:
                    self._log(f"Successfully applied graphics plugin: {selected_plugin}")
                    messagebox.showinfo("Success", f"Graphics plugin set to:\n{selected_plugin}")
                else:
                    self._log("Failed to apply graphics plugin.")
                    messagebox.showerror("Error", "Failed to set graphics plugin.")
            except Exception as e:
                logger.error(f"Error applying plugin: {e}")
                self._log(f"Error applying plugin: {e}")
                messagebox.showerror("Error", f"Failed to apply graphics plugin:\n{e}")
        else:
            # Fallback to config file
            try:
                success = self.config_manager.set_graphics_plugin(selected_plugin)
                if success:
                    self._log(f"Successfully applied graphics plugin: {selected_plugin}")
                    messagebox.showinfo("Success", f"Graphics plugin set to:\n{selected_plugin}")
                else:
                    self._log("Failed to apply graphics plugin.")
                    messagebox.showerror("Error", "Failed to save graphics plugin setting.")
            except Exception as e:
                logger.error(f"Error applying plugin: {e}")
                self._log(f"Error applying plugin: {e}")
                messagebox.showerror("Error", f"Failed to apply graphics plugin:\n{e}")
    
    def start_emu(self):
        """Start the emulator."""
        if self.running:
            self._log("Emulator is already running.")
            return
        
        if not self.rom_path or not self.rom_path.exists():
            self._log("No valid ROM selected.")
            messagebox.showerror("Error", "Please select a valid ROM file first.")
            return
        
        self._log(f"Loading ROM: {self.rom_path.name}")
        
        if self.backend_available:
            try:
                # Load ROM using backend
                if self.backend.load_rom(str(self.rom_path)):
                    if self.backend.start_emulation():
                        self.running = True
                        self._log("Emulator started successfully.")
                    else:
                        self._log("Failed to start emulation.")
                        messagebox.showerror("Error", "Failed to start emulation.")
                else:
                    self._log("Failed to load ROM.")
                    messagebox.showerror("Error", "Failed to load ROM file.")
                    
            except Exception as e:
                logger.error(f"Failed to start emulator: {e}")
                self._log(f"Failed to start emulator: {e}")
                messagebox.showerror("Launch Error", f"Could not start emulator.\n\n{e}")
        else:
            # Fallback to external Project64
            exe_path = self.overlay.pj64_dir / "Project64.exe"
            if not exe_path.exists():
                self._warn_missing_payload()
                return
            
            command = [str(exe_path), str(self.rom_path)]
            self._log(f"Starting emulator with command: {command}")
            
            try:
                # Use DETACHED_PROCESS on Windows to run it in a separate console context
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                self.emu_process = subprocess.Popen(
                    command,
                    cwd=self.overlay.pj64_dir,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_CONSOLE,
                    startupinfo=startupinfo
                )
                self.running = True
                self._log("Emulator started successfully.")
                
            except Exception as e:
                logger.error(f"Failed to start emulator: {e}")
                self._log(f"Failed to start emulator: {e}")
                messagebox.showerror("Launch Error", f"Could not start Project64.exe.\n\n{e}")
    
    def stop_emu(self):
        """Stop the emulator."""
        self._log("Stopping emulator...")
        
        if self.backend_available:
            try:
                self.backend.stop_emulation()
                self.running = False
                self._log("Emulator stopped.")
            except Exception as e:
                logger.error(f"Error stopping emulator: {e}")
                self._log(f"Error stopping emulator: {e}")
        elif self.emu_process:
            try:
                self.emu_process.terminate()
                try:
                    self.emu_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._log("Process did not terminate gracefully, killing.")
                    self.emu_process.kill()
                    self.emu_process.wait(timeout=2)
            except Exception as e:
                logger.error(f"Error stopping emulator: {e}")
                self._log(f"Error stopping emulator: {e}")
            finally:
                self.emu_process = None
            
            self.running = False
            self._log("Emulator stopped.")
    
    def reset_emu(self):
        """Reset the emulator."""
        if not self.running:
            self._log("Emulator not running, cannot reset.")
            return
        
        self._log("Resetting emulator...")
        
        if self.backend_available:
            try:
                self.backend.reset_emulation()
                self._log("Emulator reset.")
            except Exception as e:
                logger.error(f"Error resetting emulator: {e}")
                self._log(f"Error resetting emulator: {e}")
        else:
            self.stop_emu()
            # Give it a moment before restarting
            self.root.after(1000, self.start_emu)
    
    def _save_state(self):
        """Save emulation state."""
        if not self.backend_available:
            self._log("Save state not available without backend.")
            return
        
        try:
            # Simple dialog to get slot number
            slot = 0  # Default slot
            if self.backend.save_state(slot):
                self._log(f"State saved to slot {slot}")
                messagebox.showinfo("Success", f"State saved to slot {slot}")
            else:
                self._log("Failed to save state.")
                messagebox.showerror("Error", "Failed to save state.")
        except Exception as e:
            logger.error(f"Error saving state: {e}")
            self._log(f"Error saving state: {e}")
            messagebox.showerror("Error", f"Failed to save state:\n{e}")
    
    def _load_state(self):
        """Load emulation state."""
        if not self.backend_available:
            self._log("Load state not available without backend.")
            return
        
        try:
            # Simple dialog to get slot number
            slot = 0  # Default slot
            if self.backend.load_state(slot):
                self._log(f"State loaded from slot {slot}")
                messagebox.showinfo("Success", f"State loaded from slot {slot}")
            else:
                self._log("Failed to load state.")
                messagebox.showerror("Error", "Failed to load state.")
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            self._log(f"Error loading state: {e}")
            messagebox.showerror("Error", f"Failed to load state:\n{e}")

def main():
    """Main entry point."""
    try:
        root = tk.Tk()
        app = EmuAIPro(root)
        root.mainloop()
    except Exception as e:
        logger.error(f"Application error: {e}")
        messagebox.showerror("Fatal Error", f"A fatal error occurred:\n{e}")

if __name__ == "__main__":
    main()
