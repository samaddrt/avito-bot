{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    # Системные библиотеки для headless-Chromium (Playwright)
    pkgs.chromium
    pkgs.glib
    pkgs.nss
    pkgs.nspr
    pkgs.atk
    pkgs.cups
    pkgs.dbus
    pkgs.libdrm
    pkgs.mesa
    pkgs.alsa-lib
    pkgs.at-spi2-atk
    pkgs.at-spi2-core
    pkgs.cairo
    pkgs.pango
    pkgs.gtk3
    pkgs.gdk-pixbuf
    pkgs.libxkbcommon
    pkgs.xorg.libX11
    pkgs.xorg.libXcomposite
    pkgs.xorg.libXdamage
    pkgs.xorg.libXext
    pkgs.xorg.libXfixes
    pkgs.xorg.libXrandr
    pkgs.xorg.libxcb
  ];
  env = {
    # Используем системный Chromium от Nix вместо скачанного Playwright
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH = "${pkgs.chromium}/bin/chromium";
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
  };
}
