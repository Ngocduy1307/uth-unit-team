package vn.unit.affordability.dossier.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import vn.unit.affordability.dossier.dto.CreateDossierRequest;
import vn.unit.affordability.dossier.dto.DossierResponse;
import vn.unit.affordability.dossier.dto.UpdateDossierStatusRequest;
import vn.unit.affordability.dossier.service.DossierService;
import vn.unit.affordability.shared.dto.ApiResponse;

import java.util.List;

@RestController
@RequestMapping("/api/v1/dossiers")
@RequiredArgsConstructor
@Tag(name = "Dossier", description = "Quản lý hồ sơ thẩm định tín dụng")
public class DossierController {

    private final DossierService dossierService;

    @PostMapping
    @Operation(summary = "Tạo mới hồ sơ thẩm định")
    public ResponseEntity<ApiResponse<DossierResponse>> createDossier(
            @Valid @RequestBody CreateDossierRequest request) {
        DossierResponse response = dossierService.createDossier(request);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(ApiResponse.success("Dossier created successfully", response));
    }

    @GetMapping("/{id}")
    @Operation(summary = "Lấy hồ sơ theo ID")
    public ResponseEntity<ApiResponse<DossierResponse>> getDossierById(@PathVariable String id) {
        return ResponseEntity.ok(ApiResponse.success(dossierService.getDossierById(id)));
    }

    @GetMapping
    @Operation(summary = "Tìm kiếm hồ sơ theo applicantId hoặc status")
    public ResponseEntity<ApiResponse<List<DossierResponse>>> getDossiers(
            @RequestParam(required = false) String applicantId,
            @RequestParam(required = false) String status) {
        List<DossierResponse> result;
        if (applicantId != null) {
            result = dossierService.getDossiersByApplicantId(applicantId);
        } else if (status != null) {
            result = dossierService.getDossiersByStatus(status);
        } else {
            result = List.of();
        }
        return ResponseEntity.ok(ApiResponse.success(result));
    }

    @PatchMapping("/{id}/status")
    @Operation(summary = "Cập nhật trạng thái hồ sơ (Maker/Checker)")
    public ResponseEntity<ApiResponse<DossierResponse>> updateStatus(
            @PathVariable String id,
            @Valid @RequestBody UpdateDossierStatusRequest request) {
        return ResponseEntity.ok(ApiResponse.success(dossierService.updateStatus(id, request)));
    }
}
