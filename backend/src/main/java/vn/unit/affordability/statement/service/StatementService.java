package vn.unit.affordability.statement.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import vn.unit.affordability.dossier.repository.DossierRepository;
import vn.unit.affordability.shared.exception.ResourceNotFoundException;
import vn.unit.affordability.statement.dto.AdjustTransactionRequest;
import vn.unit.affordability.statement.dto.StatementAccountResponse;
import vn.unit.affordability.statement.dto.TransactionRecordResponse;
import vn.unit.affordability.statement.dto.VerifyAccountRequest;
import vn.unit.affordability.statement.model.StatementAccount;
import vn.unit.affordability.statement.model.TransactionRecord;
import vn.unit.affordability.statement.repository.StatementAccountRepository;
import vn.unit.affordability.statement.repository.TransactionRecordRepository;

import java.time.OffsetDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class StatementService {

    private final StatementAccountRepository accountRepository;
    private final TransactionRecordRepository transactionRepository;
    private final DossierRepository dossierRepository;

    public List<StatementAccountResponse> getAccountsByDossierId(String dossierId) {
        requireDossierExists(dossierId);
        return accountRepository.findByDossierId(dossierId).stream()
                .map(this::toAccountResponse)
                .toList();
    }

    public List<TransactionRecordResponse> getTransactionsByDossierId(String dossierId) {
        requireDossierExists(dossierId);
        return transactionRepository.findByDossierId(dossierId).stream()
                .map(this::toTransactionResponse)
                .toList();
    }

    public List<TransactionRecordResponse> getTransactionsByDossierAndClassification(
            String dossierId, String classification) {
        requireDossierExists(dossierId);
        return transactionRepository.findByDossierIdAndClassification(dossierId, classification).stream()
                .map(this::toTransactionResponse)
                .toList();
    }

    @Transactional
    public StatementAccountResponse verifyAccount(String accountId, VerifyAccountRequest request) {
        StatementAccount account = accountRepository.findById(accountId)
                .orElseThrow(() -> new ResourceNotFoundException("Statement account not found: " + accountId));
        account.setIsVerified(request.getIsVerified());
        account.setVerifiedBy(request.getVerifiedBy());
        account.setVerifiedAt(OffsetDateTime.now());
        if (request.getIsHolderMatched() != null) {
            account.setIsHolderMatched(request.getIsHolderMatched());
        }
        return toAccountResponse(accountRepository.save(account));
    }

    @Transactional
    public TransactionRecordResponse adjustTransaction(String transactionId, AdjustTransactionRequest request) {
        TransactionRecord record = transactionRepository.findById(transactionId)
                .orElseThrow(() -> new ResourceNotFoundException("Transaction not found: " + transactionId));
        record.setAdjustedAmount(request.getAdjustedAmount());
        record.setAdjustedBy(request.getAdjustedBy());
        record.setAdjustedAt(OffsetDateTime.now());
        record.setAdjustmentReason(request.getAdjustmentReason());
        record.setIsAccepted(request.getIsAccepted());
        if (request.getExclusionReason() != null) {
            record.setExclusionReason(request.getExclusionReason());
        }
        return toTransactionResponse(transactionRepository.save(record));
    }

    private void requireDossierExists(String dossierId) {
        if (!dossierRepository.existsById(dossierId)) {
            throw new ResourceNotFoundException("Dossier not found: " + dossierId);
        }
    }

    private StatementAccountResponse toAccountResponse(StatementAccount a) {
        return StatementAccountResponse.builder()
                .id(a.getId())
                .dossierId(a.getDossierId())
                .bankName(a.getBankName())
                .bankCode(a.getBankCode())
                .accountNumber(a.getAccountNumber())
                .accountHolderName(a.getAccountHolderName())
                .currency(a.getCurrency())
                .statementFromDate(a.getStatementFromDate())
                .statementToDate(a.getStatementToDate())
                .totalCreditAmount(a.getTotalCreditAmount())
                .totalDebitAmount(a.getTotalDebitAmount())
                .isHolderMatched(a.getIsHolderMatched())
                .matchConfidence(a.getMatchConfidence())
                .isVerified(a.getIsVerified())
                .verifiedBy(a.getVerifiedBy())
                .verifiedAt(a.getVerifiedAt())
                .createdAt(a.getCreatedAt())
                .build();
    }

    private TransactionRecordResponse toTransactionResponse(TransactionRecord t) {
        return TransactionRecordResponse.builder()
                .id(t.getId())
                .accountId(t.getAccountId())
                .dossierId(t.getDossierId())
                .transactionDate(t.getTransactionDate())
                .bookingDate(t.getBookingDate())
                .amount(t.getAmount())
                .currency(t.getCurrency())
                .direction(t.getDirection())
                .runningBalance(t.getRunningBalance())
                .description(t.getDescription())
                .classification(t.getClassification())
                .confidenceScore(t.getConfidenceScore())
                .isRecurringSalary(t.getIsRecurringSalary())
                .sourcePage(t.getSourcePage())
                .sourceRow(t.getSourceRow())
                .isAccepted(t.getIsAccepted())
                .exclusionReason(t.getExclusionReason())
                .adjustedAmount(t.getAdjustedAmount())
                .adjustedBy(t.getAdjustedBy())
                .adjustedAt(t.getAdjustedAt())
                .adjustmentReason(t.getAdjustmentReason())
                .createdAt(t.getCreatedAt())
                .build();
    }
}
