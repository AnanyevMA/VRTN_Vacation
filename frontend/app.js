const { createApp, ref, computed, onMounted, nextTick, watch } = Vue;

const app = createApp({
    components: {
        'gantt-view': window.GanttView,
        'roster-view': window.RosterView,
        'dept-roles-view': window.DeptRolesView,
        'rules-view': window.RulesView,
        'chat-view': window.ChatView,
    },
    setup() {
        const activeTab = ref('gantt');
        const selectedYear = ref(2026);
        const employees = ref([]);
        const departments = ref([]);
        const roles = ref([]);
        const shifts = ref([]);
        const vacationSlots = ref([]);
        const scheduleRules = ref([]);
        const botAdmins = ref([]);
        const stats = ref({
            total_employees: 0,
            submitted_count: 0,
            submission_rate_percent: 0,
            approved_slots_count: 0,
            pending_slots_count: 0,
            conflict_slots_count: 0,
        });

        const searchQuery = ref('');
        const isBatchProcessing = ref(false);

        // Rules state
        const roleQuotas = ref({});
        const shiftQuotas = ref({});
        const blackoutsList = ref([]);
        const incompatibleGroups = ref([]);

        // Chat state
        const selectedEmployeeId = ref(null);
        const chatMessages = ref([]);
        const userInput = ref('');
        const isTyping = ref(false);

        // Modals
        const editingSlot = ref(null);
        const showEmployeeModal = ref(false);
        const isEditingEmployee = ref(false);
        const empForm = ref({
            id: null,
            full_name: '',
            phone: '',
            role: 'Швея (портной)',
            department_id: 1,
            shift: 'Смена 1 (дневная 07:00-15:30)',
            region: 'Республика Хакасия',
            total_vacation_days: 36,
            seniority_years: 1,
            social_priority: 'NONE',
        });

        // Admin Auth State (R2)
        const adminToken = ref(localStorage.getItem('vacation_admin_token') || '');
        const showAdminModal = ref(false);
        const adminTokenInput = ref(adminToken.value);
        const adminAuthError = ref('');

        const saveAdminToken = (token) => {
            const cleanToken = (token !== undefined ? token : adminTokenInput.value || '').trim();
            adminToken.value = cleanToken;
            adminTokenInput.value = cleanToken;
            if (cleanToken) {
                localStorage.setItem('vacation_admin_token', cleanToken);
            } else {
                localStorage.removeItem('vacation_admin_token');
            }
            adminAuthError.value = '';
            showAdminModal.value = false;
            if (cleanToken) fetchAllData();
            nextTick(() => {
                if (window.lucide) window.lucide.createIcons();
            });
        };

        const clearAdminToken = () => {
            adminToken.value = '';
            adminTokenInput.value = '';
            localStorage.removeItem('vacation_admin_token');
            adminAuthError.value = '';
            nextTick(() => {
                if (window.lucide) window.lucide.createIcons();
            });
        };

        const openAdminModal = (errorMsg = '') => {
            adminTokenInput.value = adminToken.value;
            adminAuthError.value = errorMsg;
            showAdminModal.value = true;
            nextTick(() => {
                if (window.lucide) window.lucide.createIcons();
            });
        };

        const adminFetch = async (url, options = {}) => {
            const opts = { ...options };
            const headers = { ...(opts.headers || {}) };
            if (adminToken.value) {
                headers['X-Admin-Token'] = adminToken.value;
            }
            opts.headers = headers;
            const res = await fetch(url, opts);
            if (res.status === 401) {
                let detail = 'Требуется авторизация администратора (неверный или отсутствующий ключ)';
                try {
                    const errJson = await res.clone().json();
                    if (errJson.detail) detail = errJson.detail;
                } catch (_) {}
                openAdminModal(detail);
            }
            return res;
        };
        window.adminFetch = adminFetch;

        const adminJson = async (url) => {
            const res = await adminFetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
            return res.json();
        };

        const downloadExport = async (format) => {
            try {
                const res = await adminFetch(`api/export/${format}`);
                if (!res.ok) {
                    if (res.status === 401) return;
                    const err = await res.json().catch(() => ({}));
                    return alert(err.detail || 'Ошибка при экспорте данных');
                }
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const filename = format === 'excel' ? `form_t7_vacation_schedule_${selectedYear.value}.xlsx` : `vacation_schedule_${selectedYear.value}.csv`;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
            } catch (err) {
                console.error('Export download error:', err);
            }
        };

        // --- Computed ---
        const currentEmployee = computed(() => {
            return employees.value.find(e => e.id === selectedEmployeeId.value) || null;
        });

        const filteredEmployees = computed(() => {
            const q = searchQuery.value.toLowerCase().trim();
            if (!q) return employees.value;
            return employees.value.filter(emp => {
                return emp.full_name.toLowerCase().includes(q) ||
                    emp.phone.toLowerCase().includes(q) ||
                    emp.role.toLowerCase().includes(q) ||
                    (emp.shift && emp.shift.toLowerCase().includes(q)) ||
                    (emp.department_name && emp.department_name.toLowerCase().includes(q));
            });
        });

        // --- Data Fetching ---
        const fetchAllData = async () => {
            try {
                const [empRes, deptRes, rolesRes, shiftsRes, vacRes, rulesRes, statsRes, botAdminsRes, incompRes] = await Promise.all([
                    adminJson('api/employees'),
                    adminJson('api/departments'),
                    adminJson('api/roles'),
                    adminJson('api/shifts'),
                    adminJson(`api/vacations?year=${selectedYear.value}`),
                    adminJson('api/rules'),
                    adminJson('api/export/stats'),
                    adminJson('api/bot-admins'),
                    adminJson('api/rules/incompatible-groups'),
                ]);

                employees.value = empRes;
                departments.value = deptRes;
                roles.value = rolesRes;
                shifts.value = shiftsRes;
                vacationSlots.value = vacRes;
                scheduleRules.value = rulesRes;
                stats.value = statsRes;
                botAdmins.value = botAdminsRes;
                incompatibleGroups.value = incompRes;

                // Sync quotas directly from unified JobRole table
                const newQuotas = {};
                rolesRes.forEach(r => {
                    newQuotas[r.name] = r.default_quota;
                });
                roleQuotas.value = newQuotas;

                // Sync shift quotas
                const newShiftQuotas = {};
                shiftsRes.forEach(s => {
                    newShiftQuotas[s.name] = s.default_quota !== undefined ? s.default_quota : 2;
                });
                shiftQuotas.value = newShiftQuotas;

                // Sync blackouts
                const bRule = rulesRes.find(r => r.rule_key === 'blackout_periods');
                if (bRule && bRule.parameters && bRule.parameters.periods) {
                    blackoutsList.value = [...bRule.parameters.periods];
                }

                if (!selectedEmployeeId.value && employees.value.length > 0) {
                    selectedEmployeeId.value = employees.value[1] ? employees.value[1].id : employees.value[0].id;
                    loadChatHistory(selectedEmployeeId.value);
                }

                nextTick(() => {
                    if (window.lucide) window.lucide.createIcons();
                });
            } catch (err) {
                console.error('Error fetching data:', err);
            }
        };

        const loadChatHistory = async (empId) => {
            if (!empId) return;
            try {
                const res = await adminJson(`api/chat/history/${empId}`);
                chatMessages.value = res;
            } catch (e) {
                console.error('Error loading chat history:', e);
            }
        };

        const openChatFor = (emp) => {
            selectedEmployeeId.value = emp.id;
            activeTab.value = 'chat';
            loadChatHistory(emp.id);
        };

        const sendMessage = async (textToSend) => {
            const text = (textToSend || userInput.value).trim();
            if (!text || !selectedEmployeeId.value) return;

            const tempUserMsg = {
                id: Date.now(),
                sender: 'USER',
                text: text,
                timestamp: new Date().toISOString(),
                payload: null,
            };
            chatMessages.value.push(tempUserMsg);
            if (!textToSend) userInput.value = '';

            isTyping.value = true;
            try {
                const httpRes = await adminFetch('api/chat/message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ employee_id: selectedEmployeeId.value, message: text })
                });
                if (!httpRes.ok) throw new Error(`HTTP ${httpRes.status}: api/chat/message`);
                const res = await httpRes.json();

                isTyping.value = false;
                chatMessages.value.push({
                    id: Date.now() + 1,
                    sender: res.sender,
                    text: res.text,
                    timestamp: new Date().toISOString(),
                    payload: res.payload,
                });

                // Only reload all dashboard datasets when vacation slots were committed
                if (res.payload && res.payload.action === 'SUBMISSION_CONFIRMED') {
                    fetchAllData();
                }
            } catch (err) {
                isTyping.value = false;
                console.error('Error sending message:', err);
            }
        };

        const chooseAlternative = async (optionNum) => {
            await sendMessage(`${optionNum}`);
        };

        const confirmDraftSubmission = async () => {
            await sendMessage('Подтверждаю');
        };

        const setInputText = (text) => {
            userInput.value = text;
        };

        const clearChat = async () => {
            if (!selectedEmployeeId.value) return;
            const res = await adminFetch(`api/chat/reset/${selectedEmployeeId.value}`, { method: 'POST' });
            if (!res.ok) return;
            chatMessages.value = [];
            await loadChatHistory(selectedEmployeeId.value);
        };

        // --- Slot Actions ---
        const selectSlot = (slot) => {
            editingSlot.value = slot;
        };

        const updateSlotStatus = async (slotId, status) => {
            await adminFetch(`api/vacations/${slotId}/status?status=${status}`, { method: 'PUT' });
            editingSlot.value = null;
            fetchAllData();
        };

        const deleteSlot = async (slotId) => {
            await adminFetch(`api/vacations/${slotId}`, { method: 'DELETE' });
            editingSlot.value = null;
            fetchAllData();
        };

        // --- Batch Optimization ---
        const runBatchApprove = async () => {
            isBatchProcessing.value = true;
            try {
                const res = await adminFetch(`api/vacations/batch-approve?year=${selectedYear.value}`, { method: 'POST' }).then(r => r.json());
                isBatchProcessing.value = false;
                fetchAllData();
                alert(`✅ Пакетная оптимизация на ${selectedYear.value} год завершена!\n\nОдобрено слотов: ${res.approved_count}\nКоллизий выявлено: ${res.conflicts_count}`);
            } catch (err) {
                isBatchProcessing.value = false;
                alert('Ошибка при выполнении пакетной оптимизации');
            }
        };

        // --- Employee CRUD ---
        const openAddEmployeeModal = () => {
            isEditingEmployee.value = false;
            empForm.value = {
                id: null,
                full_name: '',
                phone: '+7900',
                role: roles.value[0]?.name || 'Швея (портной)',
                department_id: departments.value[0]?.id || 1,
                shift: shifts.value[0]?.name || 'Смена 1 (дневная 07:00-15:30)',
                region: 'Республика Хакасия',
                total_vacation_days: 36,
                seniority_years: 1,
                social_priority: 'NONE',
            };
            showEmployeeModal.value = true;
        };

        const editEmployee = (emp) => {
            isEditingEmployee.value = true;
            empForm.value = { ...emp };
            showEmployeeModal.value = true;
        };

        const saveEmployee = async () => {
            if (isEditingEmployee.value) {
                await adminFetch(`api/employees/${empForm.value.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(empForm.value)
                });
            } else {
                await adminFetch('api/employees', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(empForm.value)
                });
            }
            showEmployeeModal.value = false;
            fetchAllData();
        };

        const isSyncing = ref(false);

        const syncGoogleSheets = async () => {
            isSyncing.value = true;
            try {
                const res = await adminFetch('api/employees/sync-google-sheets', { method: 'POST' }).then(r => r.json());
                isSyncing.value = false;
                await fetchAllData();
                alert(`Синхронизация с Google Таблицей завершена успешно!\n\nВсего работников: ${res.total_imported}\nДобавлено новых: ${res.created}\nОбновлено: ${res.updated}`);
            } catch (err) {
                isSyncing.value = false;
                console.error('Error syncing google sheets:', err);
                alert('Ошибка при синхронизации с Google Таблицей');
            }
        };

        const toggleBotAccess = async (emp, newStatus) => {
            try {
                await adminFetch(`api/employees/${emp.id}/bot-access?status=${newStatus}`, { method: 'PUT' });
                emp.bot_access = newStatus;
            } catch (err) {
                console.error('Error toggling bot access:', err);
                alert('Ошибка изменения доступа к боту');
            }
        };

        const deleteEmployee = async (id) => {
            if (confirm('Вы уверены, что хотите удалить сотрудника?')) {
                await adminFetch(`api/employees/${id}`, { method: 'DELETE' });
                fetchAllData();
            }
        };

        // --- Rules Actions ---
        const saveRoleQuotas = async () => {
            await adminFetch('api/rules/role-quotas', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(roleQuotas.value)
            });
            alert('Квоты ролей успешно сохранены!');
            fetchAllData();
        };

        const addBlackout = async (newB) => {
            blackoutsList.value.push({ ...newB });
            await adminFetch('api/rules/blackouts', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(blackoutsList.value)
            });
            fetchAllData();
        };

        const removeBlackout = async (idx) => {
            blackoutsList.value.splice(idx, 1);
            await adminFetch('api/rules/blackouts', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(blackoutsList.value)
            });
            fetchAllData();
        };

        const saveShiftQuotas = async () => {
            await adminFetch('api/rules/shift-quotas', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(shiftQuotas.value)
            });
            alert('Квоты смен успешно сохранены в единой базе!');
            fetchAllData();
        };

        const addIncompatibleGroup = async (groupData) => {
            const res = await adminFetch('api/rules/incompatible-groups', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(groupData)
            });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка создания группы непересечения');
            }
            alert('Группа непересекающихся сотрудников успешно создана!');
            fetchAllData();
        };

        const deleteIncompatibleGroup = async (groupId) => {
            if (!confirm('Удалить эту группу непересечения сотрудников?')) return;
            const res = await adminFetch(`api/rules/incompatible-groups/${groupId}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json();
                return alert(err.detail || 'Ошибка удаления группы');
            }
            fetchAllData();
        };

        const formatDateRu = (dStr) => {
            if (!dStr) return '';
            return new Date(dStr).toLocaleDateString('ru-RU');
        };

        // Watchers
        watch(selectedYear, () => {
            fetchAllData();
        });

        watch(selectedEmployeeId, (newId) => {
            loadChatHistory(newId);
        });

        watch(activeTab, () => {
            nextTick(() => {
                if (window.lucide) window.lucide.createIcons();
            });
        });

        onMounted(() => {
            fetchAllData();
            setInterval(() => {
                // Skip while the key dialog is open: a 401 here would reset the key being typed
                if (document.hidden || showAdminModal.value) return;
                adminJson('api/export/stats').then(res => {
                    stats.value = res;
                }).catch(() => {});
            }, 30000);
        });

        return {
            activeTab,
            selectedYear,
            employees,
            departments,
            roles,
            shifts,
            vacationSlots,
            scheduleRules,
            stats,
            searchQuery,
            filteredEmployees,
            isBatchProcessing,
            roleQuotas,
            blackoutsList,
            selectedEmployeeId,
            currentEmployee,
            chatMessages,
            userInput,
            isTyping,
            editingSlot,
            showEmployeeModal,
            isEditingEmployee,
            empForm,
            fetchAllData,
            openChatFor,
            sendMessage,
            chooseAlternative,
            confirmDraftSubmission,
            setInputText,
            clearChat,
            selectSlot,
            updateSlotStatus,
            deleteSlot,
            runBatchApprove,
            openAddEmployeeModal,
            editEmployee,
            saveEmployee,
            deleteEmployee,
            saveRoleQuotas,
            addBlackout,
            removeBlackout,
            shiftQuotas,
            incompatibleGroups,
            saveShiftQuotas,
            addIncompatibleGroup,
            deleteIncompatibleGroup,
            formatDateRu,
            isSyncing,
            syncGoogleSheets,
            botAdmins,
            toggleBotAccess,
            adminToken,
            showAdminModal,
            adminTokenInput,
            adminAuthError,
            saveAdminToken,
            clearAdminToken,
            openAdminModal,
            adminFetch,
            downloadExport,
        };
    }
});

app.mount('#app');
