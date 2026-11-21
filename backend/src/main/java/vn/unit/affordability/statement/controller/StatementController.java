package vn.unit.affordability.statement.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import vn.unit.affordability.shared.dto.ApiResponse;
import vn.unit.affordability.statement.dto.AdjustTransactionRequest;
import vn.unit.affordability.statement.dto.StatementAccountResponse;
import vn.unit.affordability.statement.dto.TransactionRecordResponse;
import vn.unit.affordability.statement.dto.VerifyAccountRequest;
import vn.unit.affordability.statement.service.StatementService;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
@Tag(name = "Statement", description = "Quản lý sao kê tài khoản và sổ cái giao dịch 6 tháng")
public class StatementController {

    private final StatementService statementService;

    @GetMapping("/dossiers/{dossierId}/statement-accounts")
    @Operation(summary = "Lấy danh sách tài khoản sao kê của hồ sơ")
    public ResponseEntity<ApiResponse<List<StatementAccountResponse>>> getAccounts(
            @PathVariable String dossierId) {
        return ResponseEntity.ok(ApiResponse.success(
                statementService.getAccountsByDossierId(dossierId)));
    }

    @PatchMapping("/statement-accounts/{accountId}/verify")
    @Operation(summary = "Maker xác minh tài khoản sao kê khớp CCCD (INC 02)")
    public ResponseEntity<ApiResponse<StatementAccountResponse>> verifyAccount(
            @PathVariable String accountId,
            @Valid @RequestBody VerifyAccountRequest request) {
        return ResponseEntity.ok(ApiResponse.success(
                statementService.verifyAccount(accountId, request)));
    }

    @GetMapping("/dossiers/{dossierId}/transactions")
    @Operation(summary = "Lấy sổ cái giao dịch 6 tháng của hồ sơ")
    public ResponseEntity<ApiResponse<List<TransactionRecordResponse>>> getTransactions(
            @PathVariable String dossierId,
            @RequestParam(required = false) String classification) {
        List<TransactionRecordResponse> result = classification != null
                ? statementService.getTransactionsByDossierAndClassification(dossierId, classification)
                : statementService.getTransactionsByDossierId(dossierId);
        return ResponseEntity.ok(ApiResponse.success(result));
    }

    @PatchMapping("/transactions/{transactionId}/adjust")
    @Operation(summary = "Maker điều chỉnh / loại trừ giao dịch (INC 06)")
    public ResponseEntity<ApiResponse<TransactionRecordResponse>> adjustTransaction(
            @PathVariable String transactionId,
            @Valid @RequestBody AdjustTransactionRequest request) {
        return ResponseEntity.ok(ApiResponse.success(
                statementService.adjustTransaction(transactionId, request)));
    }
}
