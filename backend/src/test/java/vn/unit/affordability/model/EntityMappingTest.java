package vn.unit.affordability.model;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import vn.unit.affordability.dossier.model.Dossier;
import vn.unit.affordability.dossier.model.EvidenceRecord;
import vn.unit.affordability.financial.model.AffordabilitySnapshot;
import vn.unit.affordability.financial.model.Obligation;
import vn.unit.affordability.shared.audit.model.AuditLog;
import vn.unit.affordability.shared.outbox.model.OutboxEvent;
import vn.unit.affordability.statement.model.StatementAccount;
import vn.unit.affordability.statement.model.TransactionRecord;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EntityMappingTest {

    @Test
    @DisplayName("Should build Dossier with complete financial request attributes")
    void shouldBuildDossierCorrectly() {
        String id = UUID.randomUUID().toString();
        Dossier dossier = Dossier.builder()
                .id(id)
                .applicationId("APP-2026-0001")
                .applicantId("079201009999")
                .applicantName("NGUYEN VAN A")
                .bankCode("VCB")
                .status("DRAFT")
                .loanProduct("UNSECURED_CONSUMER")
                .requestedAmount(new BigDecimal("100000000.00"))
                .requestedTenorMonths(36)
                .proposedInterestRate(new BigDecimal("8.50"))
                .monthlyDeclaredLivingExpense(new BigDecimal("6000000.00"))
                .build();

        assertEquals(id, dossier.getId());
        assertEquals("APP-2026-0001", dossier.getApplicationId());
        assertEquals("DRAFT", dossier.getStatus());
        assertEquals(new BigDecimal("100000000.00"), dossier.getRequestedAmount());
        assertEquals(36, dossier.getRequestedTenorMonths());
        assertEquals(new BigDecimal("8.50"), dossier.getProposedInterestRate());
    }

    @Test
    @DisplayName("Should build EvidenceRecord with file hash and OCR metadata")
    void shouldBuildEvidenceRecordCorrectly() {
        String id = UUID.randomUUID().toString();
        EvidenceRecord evidence = EvidenceRecord.builder()
                .id(id)
                .dossierId("dossier-1")
                .fileName("sao_ke_vcb_6m.pdf")
                .fileHash("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/dossiers/dossier-1/sao_ke.pdf")
                .uploadedBy("maker_user_01")
                .fileSizeBytes(1048576L)
                .mimeType("application/pdf")
                .build();

        assertEquals("RECEIVED", evidence.getStatus());
        assertEquals("PENDING", evidence.getOcrStatus());
        assertEquals("sao_ke_vcb_6m.pdf", evidence.getFileName());
        assertEquals(1048576L, evidence.getFileSizeBytes());
    }

    @Test
    @DisplayName("Should build StatementAccount with account matching flags")
    void shouldBuildStatementAccountCorrectly() {
        String id = UUID.randomUUID().toString();
        StatementAccount account = StatementAccount.builder()
                .id(id)
                .dossierId("dossier-1")
                .bankName("Vietcombank")
                .bankCode("VCB")
                .accountNumber("0071000123456")
                .accountHolderName("NGUYEN VAN A")
                .statementFromDate(LocalDate.of(2026, 1, 1))
                .statementToDate(LocalDate.of(2026, 6, 30))
                .isHolderMatched(true)
                .matchConfidence(new BigDecimal("98.50"))
                .build();

        assertEquals("VND", account.getCurrency());
        assertTrue(account.getIsHolderMatched());
        assertFalse(account.getIsVerified());
        assertEquals(BigDecimal.ZERO, account.getTotalCreditAmount());
    }

    @Test
    @DisplayName("Should build TransactionRecord with lineage and classification")
    void shouldBuildTransactionRecordCorrectly() {
        String id = UUID.randomUUID().toString();
        TransactionRecord record = TransactionRecord.builder()
                .id(id)
                .accountId("acc-1")
                .dossierId("dossier-1")
                .transactionDate(LocalDate.of(2026, 5, 5))
                .amount(new BigDecimal("25000000.00"))
                .direction("CREDIT")
                .description("CTY ABC TRA LUONG T5/2026")
                .classification("SALARY_CANDIDATE")
                .confidenceScore(new BigDecimal("95.00"))
                .isRecurringSalary(true)
                .sourcePage(2)
                .sourceRow(14)
                .isAccepted(true)
                .build();

        assertEquals("SALARY_CANDIDATE", record.getClassification());
        assertTrue(record.getIsRecurringSalary());
        assertTrue(record.getIsAccepted());
        assertEquals(2, record.getSourcePage());
        assertEquals(14, record.getSourceRow());
    }

    @Test
    @DisplayName("Should build Obligation with declared and CIC parameters")
    void shouldBuildObligationCorrectly() {
        String id = UUID.randomUUID().toString();
        Obligation obligation = Obligation.builder()
                .id(id)
                .dossierId("dossier-1")
                .institutionName("FE CREDIT")
                .obligationType("UNSECURED_LOAN")
                .monthlyPayment(new BigDecimal("2500000.00"))
                .totalBalance(new BigDecimal("20000000.00"))
                .remainingTenorMonths(8)
                .source("CIC")
                .isDuplicated(false)
                .isIncludedInDti(true)
                .build();

        assertEquals("CIC", obligation.getSource());
        assertFalse(obligation.getIsDuplicated());
        assertTrue(obligation.getIsIncludedInDti());
        assertEquals(new BigDecimal("2500000.00"), obligation.getMonthlyPayment());
    }

    @Test
    @DisplayName("Should build AffordabilitySnapshot with baseline and stress metrics")
    void shouldBuildAffordabilitySnapshotCorrectly() {
        String id = UUID.randomUUID().toString();
        AffordabilitySnapshot snapshot = AffordabilitySnapshot.builder()
                .id(id)
                .dossierId("dossier-1")
                .snapshotVersion(1)
                .formulaVersion("V1")
                .eligibleNetIncome(new BigDecimal("25000000.00"))
                .declaredLivingExpenses(new BigDecimal("5000000.00"))
                .floorLivingExpenses(new BigDecimal("6000000.00"))
                .effectiveLivingExpenses(new BigDecimal("6000000.00"))
                .existingDebtService(new BigDecimal("2500000.00"))
                .proposedLoanAmount(new BigDecimal("100000000.00"))
                .proposedLoanTenorMonths(36)
                .proposedInterestRate(new BigDecimal("8.50"))
                .proposedLoanPayment(new BigDecimal("3156000.00"))
                .baselineResidual(new BigDecimal("13344000.00"))
                .baselineDti(new BigDecimal("0.2262"))
                .stress1Residual(new BigDecimal("8344000.00"))
                .stress1Dti(new BigDecimal("0.2828"))
                .stress2Residual(new BigDecimal("7744000.00"))
                .stress2Dti(new BigDecimal("0.2828"))
                .policyStatus("PASS")
                .calculatedBy("maker_01")
                .build();

        assertEquals("PASS", snapshot.getPolicyStatus());
        assertEquals(new BigDecimal("0.5000"), snapshot.getMaxDtiLimit());
        assertEquals(new BigDecimal("5000000.00"), snapshot.getMinResidualLimit());
        assertEquals(new BigDecimal("13344000.00"), snapshot.getBaselineResidual());
    }

    @Test
    @DisplayName("Should build AuditLog and OutboxEvent correctly")
    void shouldBuildAuditLogAndOutboxEventCorrectly() {
        String auditId = UUID.randomUUID().toString();
        AuditLog audit = AuditLog.builder()
                .id(auditId)
                .dossierId("dossier-1")
                .entityName("TRANSACTION")
                .entityId("tx-123")
                .action("OVERRIDE")
                .fieldName("is_accepted")
                .oldValue("false")
                .newValue("true")
                .actorId("maker_01")
                .actorRole("MAKER")
                .reason("Khách hàng cung cấp bổ sung phụ lục hợp đồng lao động")
                .build();

        assertEquals("OVERRIDE", audit.getAction());
        assertEquals("MAKER", audit.getActorRole());
        assertNotNull(audit.getReason());

        String outboxId = UUID.randomUUID().toString();
        OutboxEvent outbox = OutboxEvent.builder()
                .id(outboxId)
                .aggregateType("DOSSIER")
                .aggregateId("dossier-1")
                .eventType("DOSSIER_SUBMITTED")
                .payload("{\"dossierId\":\"dossier-1\"}")
                .build();

        assertEquals("PENDING", outbox.getStatus());
        assertEquals(0, outbox.getRetryCount());
    }
}
