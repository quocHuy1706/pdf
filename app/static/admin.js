let CURRENT_USERS = [];

function renderUsers(users) {
    const tbody = document.getElementById("users_table");
    tbody.innerHTML = "";
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);">Không tìm thấy người dùng phù hợp.</td></tr>';
        return;
    }
    users.forEach(user => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${user.id}</td>
            <td>${user.full_name}</td>
            <td>${user.email}</td>
            <td>${user.role}</td>
            <td class="actions">
                <button class="btn small outline" onclick="toggleRole(${user.id})">Đổi quyền</button>
                <button class="btn small danger" onclick="deleteUser(${user.id})">Xóa</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadAdminData() {
    // Tổng số liệu
    const statsRes = await fetch("/admin");
    const stats = await statsRes.json();
    document.getElementById("total_users").innerText = stats.total_users;
    document.getElementById("total_documents").innerText = stats.total_documents;
    document.getElementById("total_exams").innerText = stats.total_exams;

    // Danh sách người dùng
    const usersRes = await fetch("/admin/users");
    CURRENT_USERS = await usersRes.json();
    renderUsers(CURRENT_USERS);

    // Activity Log
    const logRes = await fetch("/admin/activity");
    const logs = await logRes.json();
    const logTbody = document.getElementById("activity_log_table");
    logTbody.innerHTML = "";
    if (logs.length === 0) {
        logTbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);">Chưa có hoạt động nào.</td></tr>';
    }
    logs.forEach(log => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${log.id}</td>
            <td>${log.user_id ?? ""}</td>
            <td>${log.action}</td>
            <td>${log.timestamp ? new Date(log.timestamp).toLocaleString("vi-VN") : ""}</td>
        `;
        logTbody.appendChild(tr);
    });
}

async function deleteUser(userId) {
    if (!confirm("Bạn có chắc muốn xóa người dùng này?")) return;

    const res = await fetch(`/admin/users/${userId}`, { method: "DELETE" });
    const data = await res.json();
    if (!res.ok) {
        alert(data.detail || "Có lỗi xảy ra.");
        return;
    }
    alert(data.message);
    loadAdminData();
}

async function toggleRole(userId) {
    if (!confirm("Đổi quyền của người dùng này?")) return;

    const res = await fetch(`/admin/users/${userId}/role`, { method: "PATCH" });
    const data = await res.json();
    if (!res.ok) {
        alert(data.detail || "Có lỗi xảy ra.");
        return;
    }
    alert(`${data.message}: ${data.role}`);
    loadAdminData();
}

document.addEventListener("DOMContentLoaded", () => {
    loadAdminData();

    const searchInput = document.getElementById("user-search");
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            const q = searchInput.value.trim().toLowerCase();
            const filtered = CURRENT_USERS.filter(
                u => u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
            );
            renderUsers(filtered);
        });
    }
});
