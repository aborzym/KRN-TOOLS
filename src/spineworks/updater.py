from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QTextBlockFormat, QTextCursor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from spineworks.updates import UpdateInfo, release_history_notes, update_from_release

LATEST_RELEASE_API_URL = "https://api.github.com/repos/aborzym/KRN-TOOLS/releases/latest"


class UpdateManager(QObject):
    def __init__(
        self,
        parent: QWidget,
        *,
        settings: QSettings,
        current_version: str,
    ) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.settings = settings
        self.current_version = current_version
        self.network_manager = QNetworkAccessManager(self)
        self.download_reply: QNetworkReply | None = None
        self.download_progress: QProgressDialog | None = None
        self.download_directory: Path | None = None
        self.download_path: Path | None = None
        self.install_process: QProcess | None = None

    def check_for_updates(self, *, show_current_message: bool = False) -> None:
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(
            b"User-Agent",
            f"SPINEWORKS/{self.current_version}".encode("ascii"),
        )

        reply = self.network_manager.get(request)
        reply.finished.connect(
            lambda: self._finish_update_check(
                reply,
                show_current_message=show_current_message,
            )
        )

        if show_current_message:
            self._show_status("Sprawdzanie dostępności aktualizacji…")

    def _finish_update_check(
        self,
        reply: QNetworkReply,
        *,
        show_current_message: bool,
    ) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        response = bytes(reply.readAll())
        network_error = reply.error()
        error_text = reply.errorString()
        reply.deleteLater()

        if show_current_message:
            self._show_status("")

        if (
            network_error != QNetworkReply.NetworkError.NoError
            or status is None
            or not 200 <= int(status) < 300
        ):
            if show_current_message:
                QMessageBox.warning(
                    self.parent_widget,
                    "Nie można sprawdzić aktualizacji",
                    "Nie udało się połączyć z serwisem GitHub.\n\n"
                    f"Kod HTTP: {status or 'brak'}\n"
                    f"{error_text}",
                )
            return

        try:
            release = json.loads(response.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            if show_current_message:
                QMessageBox.warning(
                    self.parent_widget,
                    "Nie można sprawdzić aktualizacji",
                    "GitHub zwrócił nieprawidłowe dane wydania.",
                )
            return

        if not isinstance(release, dict):
            return

        skipped_version = ""
        if not show_current_message:
            stored_value = self.settings.value(
                "updates/skipped_version",
                "",
            )
            skipped_version = str(stored_value or "")

        update = update_from_release(
            release,
            current_version=self.current_version,
            platform_name=sys.platform,
            machine=platform.machine(),
            skipped_version=skipped_version,
        )

        if update is None:
            if show_current_message:
                QMessageBox.information(
                    self.parent_widget,
                    "Brak aktualizacji",
                    "Używasz najnowszej wersji programu dostępnej dla tego systemu.",
                )
            return

        self._show_status("Pobieranie historii zmian…")
        self._fetch_release_history(update, [release])

    def _fetch_release_history(
        self,
        update: UpdateInfo,
        releases: list[dict],
        *,
        page: int = 1,
    ) -> None:
        url = f"https://api.github.com/repos/aborzym/KRN-TOOLS/releases?per_page=100&page={page}"
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(
            b"User-Agent",
            f"SPINEWORKS/{self.current_version}".encode("ascii"),
        )
        request.setTransferTimeout(15000)

        reply = self.network_manager.get(request)
        reply.finished.connect(
            lambda: self._finish_release_history(
                reply,
                update,
                releases,
                page=page,
            )
        )

    def _finish_release_history(
        self,
        reply: QNetworkReply,
        update: UpdateInfo,
        releases: list[dict],
        *,
        page: int,
    ) -> None:
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        response = bytes(reply.readAll())
        network_error = reply.error()
        reply.deleteLater()

        if (
            network_error != QNetworkReply.NetworkError.NoError
            or status is None
            or not 200 <= int(status) < 300
        ):
            self._show_history_fallback(update)
            return

        try:
            batch = json.loads(response.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._show_history_fallback(update)
            return

        if not isinstance(batch, list) or any(not isinstance(release, dict) for release in batch):
            self._show_history_fallback(update)
            return

        collected = [*releases, *batch]

        if len(batch) == 100:
            self._fetch_release_history(
                update,
                collected,
                page=page + 1,
            )
            return

        notes = release_history_notes(
            collected,
            current_version=self.current_version,
            latest_version=update.version,
        )
        self._show_status("")
        self._show_update_dialog(replace(update, notes=notes))

    def _show_history_fallback(self, update: UpdateInfo) -> None:
        notes = (
            "Nie udało się pobrać pełnej historii zmian. "
            "Poniżej opis najnowszego wydania.\n\n" + update.notes
        )
        self._show_status("")
        self._show_update_dialog(replace(update, notes=notes))

    def _show_update_dialog(self, update: UpdateInfo) -> None:
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("Aktualizacja SPINEWORKS")
        dialog.resize(820, 620)
        dialog.setMinimumSize(740, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        title = QLabel(
            f"SPINEWORKS {update.version}",
            dialog,
        )
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel(
            f"Dostępna aktualizacja · Twoja wersja: {self.current_version}",
            dialog,
        )
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setStyleSheet("font-size: 13px;")
        layout.addWidget(subtitle)

        description = QLabel("Co nowego od Twojej wersji", dialog)
        description.setStyleSheet("font-size: 15px; font-weight: 600; margin-top: 8px;")
        layout.addWidget(description)

        notes = QTextBrowser(dialog)
        notes.setOpenExternalLinks(True)
        notes.setObjectName("updateHistory")
        notes.setStyleSheet(
            "QTextBrowser#updateHistory {"
            " background-color: #09120d;"
            " color: #e5efe8;"
            " border: 1px solid #355344;"
            " border-radius: 10px;"
            " padding: 14px;"
            " font-size: 14px;"
            "}"
            "QTextBrowser#updateHistory QWidget {"
            " background-color: #09120d;"
            "}"
        )
        notes.document().setDefaultStyleSheet(
            "body { font-size: 14px; }"
            "h1 { font-size: 21px; margin-top: 20px; margin-bottom: 10px; }"
            "h2 { font-size: 18px; margin-top: 18px; margin-bottom: 8px; }"
            "h3 { font-size: 15px; margin-top: 14px; margin-bottom: 6px; }"
            "p { margin-top: 6px; margin-bottom: 10px; }"
            "li { margin-bottom: 6px; }"
        )
        notes.setMarkdown(update.notes.strip() or "Autor nie dołączył opisu zmian do tego wydania.")
        document = notes.document()
        document.setDocumentMargin(22)

        block = document.begin()
        while block.isValid():
            cursor = QTextCursor(block)
            block_format = block.blockFormat()
            heading_level = block_format.headingLevel()

            block_format.setLineHeight(
                140,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )

            if heading_level == 1:
                block_format.setTopMargin(8 if block == document.begin() else 32)
                block_format.setBottomMargin(18)
            elif heading_level:
                block_format.setTopMargin(26)
                block_format.setBottomMargin(12)
            elif block.textList() is not None:
                block_format.setTopMargin(4)
                block_format.setBottomMargin(10)
            else:
                block_format.setTopMargin(8)
                block_format.setBottomMargin(14)

            cursor.setBlockFormat(block_format)
            block = block.next()

        layout.addWidget(notes, 1)
        layout.addWidget(notes, 1)

        size_megabytes = update.asset_size / (1024 * 1024)
        details = QLabel(
            f"Plik: {update.asset_name}<br>Rozmiar: {size_megabytes:.1f} MB",
            dialog,
        )
        details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(details)

        buttons = QDialogButtonBox(dialog)
        install_button = buttons.addButton(
            "Pobierz i zainstaluj",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        later_button = buttons.addButton(
            "Przypomnij później",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        skip_button = buttons.addButton(
            f"Pomiń wersję {update.version}",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        release_button = buttons.addButton(
            "Strona wydania",
            QDialogButtonBox.ButtonRole.ActionRole,
        )

        install_button.clicked.connect(dialog.accept)
        install_button.setDefault(True)
        install_button.setMinimumHeight(36)
        later_button.clicked.connect(dialog.reject)
        skip_button.clicked.connect(lambda: self._skip_version(update.version, dialog))
        release_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(update.release_url)))

        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._download_update(update)

    def _skip_version(self, version: str, dialog: QDialog) -> None:
        self.settings.setValue("updates/skipped_version", version)
        self.settings.sync()
        dialog.reject()
        self._show_status(f"Pominięto aktualizację {version}")

    def _download_update(self, update: UpdateInfo) -> None:
        self.download_directory = Path(tempfile.mkdtemp(prefix="spineworks-update-"))
        self.download_path = self.download_directory / update.asset_name

        request = QNetworkRequest(QUrl(update.asset_url))
        request.setRawHeader(
            b"User-Agent",
            f"SPINEWORKS/{self.current_version}".encode("ascii"),
        )

        reply = self.network_manager.get(request)
        self.download_reply = reply

        progress = QProgressDialog(
            f"Pobieranie SPINEWORKS {update.version}…",
            "Anuluj",
            0,
            update.asset_size,
            self.parent_widget,
        )
        progress.setWindowTitle("Aktualizacja SPINEWORKS")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self.download_progress = progress

        reply.downloadProgress.connect(
            lambda received, total: self._update_download_progress(
                received,
                total,
                update.asset_size,
            )
        )
        progress.canceled.connect(reply.abort)
        reply.finished.connect(lambda: self._finish_update_download(reply, update))

        progress.show()
        self._show_status(f"Pobieranie SPINEWORKS {update.version}…")

    def _update_download_progress(
        self,
        received: int,
        total: int,
        expected_size: int,
    ) -> None:
        if self.download_progress is None:
            return

        maximum = total if total > 0 else expected_size
        self.download_progress.setMaximum(maximum)
        self.download_progress.setValue(max(received, 0))

    def _finish_update_download(
        self,
        reply: QNetworkReply,
        update: UpdateInfo,
    ) -> None:
        if self.download_progress is not None:
            self.download_progress.close()
            self.download_progress.deleteLater()
            self.download_progress = None

        network_error = reply.error()
        error_text = reply.errorString()
        data = bytes(reply.readAll())
        reply.deleteLater()
        self.download_reply = None

        if network_error == QNetworkReply.NetworkError.OperationCanceledError:
            self._clear_download()
            self._show_status("Anulowano pobieranie aktualizacji")
            return

        if network_error != QNetworkReply.NetworkError.NoError:
            self._clear_download()
            QMessageBox.warning(
                self.parent_widget,
                "Nie udało się pobrać aktualizacji",
                error_text,
            )
            return

        if len(data) != update.asset_size:
            self._clear_download()
            QMessageBox.warning(
                self.parent_widget,
                "Nieprawidłowy plik aktualizacji",
                "Rozmiar pobranego pliku nie zgadza się z danymi opublikowanymi na GitHubie.",
            )
            return

        calculated_sha256 = hashlib.sha256(data).hexdigest()
        if calculated_sha256 != update.asset_sha256:
            self._clear_download()
            QMessageBox.critical(
                self.parent_widget,
                "Nieprawidłowa suma kontrolna",
                "Pobrany instalator nie przeszedł kontroli SHA-256 i nie zostanie uruchomiony.",
            )
            return

        if self.download_path is None:
            self._clear_download()
            return

        try:
            self.download_path.write_bytes(data)
        except OSError as error:
            self._clear_download()
            QMessageBox.warning(
                self.parent_widget,
                "Nie można zapisać aktualizacji",
                str(error),
            )
            return

        self._show_status("Pobrano i zweryfikowano aktualizację")
        self._install_update(update)

    def _install_update(self, update: UpdateInfo) -> None:
        if self.download_path is None:
            return

        if sys.platform.startswith("linux"):
            self._install_linux_update(update)
            return

        if sys.platform == "darwin":
            self._install_macos_update(update)
            return

        QMessageBox.information(
            self.parent_widget,
            "Pobrano aktualizację",
            f"Instalator zapisano w:\n{self.download_path}",
        )

    def _install_macos_update(self, update: UpdateInfo) -> None:
        if self.download_path is None or self.download_directory is None:
            return

        application_path = self._macos_application_path()
        if application_path is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.download_path)))
            QMessageBox.warning(
                self.parent_widget,
                "Nie można automatycznie zainstalować aktualizacji",
                "Nie udało się ustalić położenia aplikacji SPINEWORKS.\n\n"
                "Otworzono pobrany instalator DMG. Zastąp aplikację ręcznie.",
            )
            return

        if not application_path.exists():
            QMessageBox.warning(
                self.parent_widget,
                "Nie można automatycznie zainstalować aktualizacji",
                f"Nie znaleziono aplikacji:\n{application_path}",
            )
            return

        helper_path = self.download_directory / "install-macos-update.sh"
        try:
            helper_path.write_text(
                self._macos_update_script(),
                encoding="utf-8",
            )
        except OSError as error:
            QMessageBox.warning(
                self.parent_widget,
                "Nie można przygotować aktualizacji",
                str(error),
            )
            return

        QMessageBox.information(
            self.parent_widget,
            "Aktualizacja jest gotowa",
            f"SPINEWORKS {update.version} został pobrany i sprawdzony.\n\n"
            "Program zostanie zamknięty, aplikacja zaktualizowana "
            "i uruchomiona ponownie.",
        )

        started = QProcess.startDetached(
            "/bin/sh",
            [
                str(helper_path),
                str(self.download_path),
                str(application_path),
                str(self.download_directory),
                str(os.getpid()),
                update.version,
            ],
        )
        if isinstance(started, tuple):
            started = started[0]

        if not started:
            QMessageBox.warning(
                self.parent_widget,
                "Nie można uruchomić aktualizacji",
                "Nie udało się uruchomić procesu instalującego aktualizację.\n\n"
                f"Instalator pozostawiono w:\n{self.download_path}",
            )
            return

        QApplication.quit()

    @staticmethod
    def _macos_application_path() -> Path | None:
        executable = Path(sys.executable).resolve()
        for candidate in (executable, *executable.parents):
            if candidate.suffix == ".app":
                return candidate

        installed_application = Path("/Applications/SPINEWORKS.app")
        if installed_application.exists():
            return installed_application

        return None

    @staticmethod
    def _macos_update_script() -> str:
        return """#!/bin/sh
set -u

dmg_path=$1
target_app=$2
work_directory=$3
old_pid=$4
expected_version=$5

mount_point="$work_directory/mount"
log_path="$work_directory/update.log"
target_parent=$(dirname "$target_app")
staging_app="$target_parent/.SPINEWORKS-update-new-$$.app"
backup_app="$target_parent/.SPINEWORKS-update-backup-$$.app"
mounted=0
backup_created=0

report_failure() {
    message=$1

    if [ "$mounted" -eq 1 ]; then
        /usr/bin/hdiutil detach "$mount_point" -force >>"$log_path" 2>&1 || true
        mounted=0
    fi

    if [ "$backup_created" -eq 1 ] && [ ! -e "$target_app" ] && [ -e "$backup_app" ]; then
        /bin/mv "$backup_app" "$target_app" >>"$log_path" 2>&1 || true
    fi

    /bin/rm -rf "$staging_app"
    /usr/bin/osascript -e \
        'display alert "Aktualizacja SPINEWORKS nie powiodła się" message "'"$message"'

Szczegóły zapisano w:
'"$log_path"'" as critical buttons {"OK"} default button "OK"' \
        >/dev/null 2>&1 || true
    exit 1
}

: >"$log_path" || exit 1
/bin/mkdir -p "$mount_point" >>"$log_path" 2>&1 \
    || report_failure "Nie można przygotować katalogu instalacyjnego."

wait_count=0
while /bin/kill -0 "$old_pid" 2>/dev/null; do
    /bin/sleep 0.25
    wait_count=$((wait_count + 1))
    if [ "$wait_count" -ge 120 ]; then
        report_failure "Poprzednia wersja programu nie zakończyła pracy."
    fi
done

/usr/bin/hdiutil attach -nobrowse -readonly -mountpoint "$mount_point" "$dmg_path" \
    >>"$log_path" 2>&1 \
    || report_failure "Nie można otworzyć obrazu DMG."
mounted=1

source_app="$mount_point/SPINEWORKS.app"
if [ ! -d "$source_app" ]; then
    report_failure "Obraz DMG nie zawiera aplikacji SPINEWORKS."
fi

/usr/bin/ditto "$source_app" "$staging_app" >>"$log_path" 2>&1 \
    || report_failure "Nie można skopiować nowej wersji aplikacji."

/usr/bin/codesign --verify --deep --strict "$staging_app" >>"$log_path" 2>&1 \
    || report_failure "Podpis nowej aplikacji jest nieprawidłowy."

installed_version=$(
    /usr/libexec/PlistBuddy \
        -c "Print :CFBundleShortVersionString" \
        "$staging_app/Contents/Info.plist" 2>>"$log_path"
)
if [ "$installed_version" != "$expected_version" ]; then
    report_failure "Wersja aplikacji w obrazie DMG jest nieprawidłowa."
fi

/bin/mv "$target_app" "$backup_app" >>"$log_path" 2>&1 \
    || report_failure "Nie można utworzyć kopii zapasowej poprzedniej wersji."
backup_created=1

if ! /bin/mv "$staging_app" "$target_app" >>"$log_path" 2>&1; then
    /bin/mv "$backup_app" "$target_app" >>"$log_path" 2>&1 || true
    backup_created=0
    report_failure "Nie można zainstalować nowej wersji aplikacji."
fi

/usr/bin/hdiutil detach "$mount_point" >>"$log_path" 2>&1 \
    || /usr/bin/hdiutil detach "$mount_point" -force >>"$log_path" 2>&1 \
    || true
mounted=0

/usr/bin/open "$target_app" >>"$log_path" 2>&1 \
    || report_failure "Aktualizacja została zainstalowana, ale nie można uruchomić aplikacji."

/bin/rm -rf "$backup_app"
backup_created=0
/bin/rm -rf "$work_directory"
exit 0
"""

    def _install_linux_update(self, update: UpdateInfo) -> None:
        if self.download_path is None:
            return

        pkexec = shutil.which("pkexec")
        apt = shutil.which("apt")

        if pkexec is None or apt is None:
            QMessageBox.warning(
                self.parent_widget,
                "Nie można uruchomić instalatora",
                "Nie znaleziono programu pkexec lub apt.\n\n"
                f"Instalator pozostawiono w:\n{self.download_path}",
            )
            return

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(
            lambda exit_code, _exit_status: self._finish_linux_install(
                exit_code,
                update,
            )
        )
        process.errorOccurred.connect(lambda _error: self._linux_install_start_error(process))

        self.install_process = process
        self._show_status("Oczekiwanie na potwierdzenie instalacji aktualizacji…")
        process.start(
            pkexec,
            [
                apt,
                "install",
                "-y",
                str(self.download_path),
            ],
        )

    def _linux_install_start_error(self, process: QProcess) -> None:
        QMessageBox.warning(
            self.parent_widget,
            "Nie można uruchomić aktualizacji",
            process.errorString(),
        )
        self.install_process = None

    def _finish_linux_install(
        self,
        exit_code: int,
        update: UpdateInfo,
    ) -> None:
        output = ""
        if self.install_process is not None:
            output = bytes(self.install_process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            )
            self.install_process.deleteLater()
            self.install_process = None

        if exit_code != 0:
            QMessageBox.warning(
                self.parent_widget,
                "Aktualizacja nie została zainstalowana",
                f"Instalator zakończył pracę z błędem.\n\n{output[-4000:]}",
            )
            return

        self._clear_download()

        QMessageBox.information(
            self.parent_widget,
            "Aktualizacja zakończona",
            f"Zainstalowano SPINEWORKS {update.version}. Program zostanie uruchomiony ponownie.",
        )

        launcher = shutil.which("spineworks") or "/usr/bin/spineworks"
        QProcess.startDetached(launcher, [])
        QApplication.quit()

    def _clear_download(self) -> None:
        if self.download_directory is not None:
            shutil.rmtree(self.download_directory, ignore_errors=True)

        self.download_directory = None
        self.download_path = None

    def _show_status(self, message: str) -> None:
        status_bar_method = getattr(
            self.parent_widget,
            "statusBar",
            None,
        )
        if callable(status_bar_method):
            status_bar_method().showMessage(message)
