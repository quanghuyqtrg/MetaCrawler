# Quy trình làm việc với Git (Git Workflow)

Dự án này áp dụng mô hình **Gitflow** (đã tinh gọn) để quản lý mã nguồn, đảm bảo sự ổn định và dễ dàng phát triển tính năng mới.

## 1. Các nhánh chính (Main Branches)

Dự án có 2 nhánh tồn tại vĩnh viễn:

*   **`main`**:
    *   Chứa mã nguồn ổn định, sẵn sàng để triển khai (production-ready).
    *   Chỉ merge vào `main` khi đã kiểm thử kỹ càng.
*   **`develop`**:
    *   Nhánh phát triển chính.
    *   Chứa các tính năng mới nhất đã hoàn thiện.
    *   Mọi tính năng mới đều được merge vào đây trước khi release sang `main`.

## 2. Các nhánh hỗ trợ (Supporting Branches)

### a. Nhánh tính năng (`feature/*`)
*   **Mục đích**: Phát triển tính năng mới.
*   **Xuất phát từ**: `develop`
*   **Merge lại vào**: `develop`
*   **Quy tắc đặt tên**: `feature/ten-tinh-nang` (ví dụ: `feature/content-crawler`, `feature/login-page`)

**Quy trình:**
1.  Tạo nhánh mới từ `develop`:
    ```bash
    git checkout develop
    git pull origin develop
    git checkout -b feature/ten-tinh-nang
    ```
2.  Code, commit và push lên remote.
3.  Tạo Pull Request (PR) để merge vào `develop`.

### b. Nhánh sửa lỗi nóng (`hotfix/*`)
*   **Mục đích**: Sửa lỗi nghiêm trọng trên production ngay lập tức.
*   **Xuất phát từ**: `main`
*   **Merge lại vào**: `main` VÀ `develop`
*   **Quy tắc đặt tên**: `hotfix/ten-loi` (ví dụ: `hotfix/fix-login-error`)

**Quy trình:**
1.  Tạo nhánh từ `main`:
    ```bash
    git checkout main
    git pull origin main
    git checkout -b hotfix/ten-loi
    ```
2.  Sửa lỗi và commit.
3.  Merge vào `main` (để fix production) và `develop` (để code mới cũng có fix này).

### c. Nhánh phát hành (`release/*`) - (Tùy chọn)
*   **Mục đích**: Chuẩn bị cho một phiên bản mới (version bump, changelog generation).
*   **Xuất phát từ**: `develop`
*   **Merge lại vào**: `main` VÀ `develop`

## 3. Tóm tắt các lệnh thường dùng

| Hành động | Lệnh Git |
| :--- | :--- |
| **Bắt đầu tính năng mới** | `git checkout develop` -> `git checkout -b feature/xyz` |
| **Cập nhật code mới nhất** | `git pull origin develop` |
| **Lưu thay đổi** | `git add .` -> `git commit -m "mô tả"` |
| **Đẩy code lên server** | `git push origin feature/xyz` |
| **Hoàn thành tính năng** | Merge `feature/xyz` -> `develop` |

## 4. Ví dụ thực tế

**Tình huống**: Bạn muốn thêm tính năng "Content Crawler".

1.  **Chuyển sang nhánh develop**:
    ```bash
    git checkout develop
    ```
2.  **Tạo nhánh feature**:
    ```bash
    git checkout -b feature/content-crawler
    ```
3.  **Code và commit**:
    ```bash
    git add .
    git commit -m "feat: add crawler service"
    ```
4.  **Merge vào develop (sau khi xong)**:
    ```bash
    git checkout develop
    git merge feature/content-crawler
    ```
