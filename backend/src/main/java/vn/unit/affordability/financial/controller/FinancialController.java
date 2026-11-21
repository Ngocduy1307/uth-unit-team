package vn.unit.affordability.financial.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import vn.unit.affordability.financial.dto.AffordabilitySnapshotResponse;
import vn.unit.affordability.financial.dto.CreateObligationRequest;
import vn.unit.affordability.financial.dto.EvaluateAffordabilityRequest;
import vn.unit.affordability.financial.dto.ObligationResponse;
import vn.unit.affordability.financial.service.FinancialService;
import vn.unit.affordability.shared.dto.ApiResponse;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
@Tag(name = "Financial", description = "Phân tích tài chính: DTI, Thặng dư & Stress-test 3 kịch bản")
public class FinancialController {

    private final FinancialService financialService;

    @PostMapping("/obligations")
    @Operation(summary = "Thêm nghĩa vụ nợ hiện tại (tự khai hoặc CIC)")
    public ResponseEntity<ApiResponse<ObligationResponse>> createObligation(
            @Valid @RequestBody CreateObligationRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success("Obligation created", financialService.createObligation(request)));
    }

    @GetMapping("/dossiers/{dossierId}/obligations")
    @Operation(summary = "Lấy danh sách nghĩa vụ nợ của hồ sơ")
    public ResponseEntity<ApiResponse<List<ObligationResponse>>> getObligations(
            @PathVariable String dossierId) {
        return ResponseEntity.ok(ApiResponse.success(
                financialService.getObligationsByDossierId(dossierId)));
    }

    @PostMapping("/financial/evaluate")
    @Operation(summary = "Tính toán khả năng trả nợ: DTI, Thặng dư R và 3 kịch bản Stress-test (AFF 01-09)")
    public ResponseEntity<ApiResponse<AffordabilitySnapshotResponse>> evaluate(
            @Valid @RequestBody EvaluateAffordabilityRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success("Affordability evaluated", financialService.evaluate(request)));
    }

    @GetMapping("/dossiers/{dossierId}/snapshots")
    @Operation(summary = "Lấy lịch sử toàn bộ phiên bản thẩm định của hồ sơ")
    public ResponseEntity<ApiResponse<List<AffordabilitySnapshotResponse>>> getSnapshots(
            @PathVariable String dossierId) {
        return ResponseEntity.ok(ApiResponse.success(
                financialService.getSnapshotsByDossierId(dossierId)));
    }

    @GetMapping("/dossiers/{dossierId}/snapshots/latest")
    @Operation(summary = "Lấy kết quả thẩm định mới nhất của hồ sơ")
    public ResponseEntity<ApiResponse<AffordabilitySnapshotResponse>> getLatestSnapshot(
            @PathVariable String dossierId) {
        return ResponseEntity.ok(ApiResponse.success(
                financialService.getLatestSnapshot(dossierId)));
    }
}
